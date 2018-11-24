import torch
from torch.nn.parallel import DataParallel
from .distributed_model import MGANModel
import random


class MGANTrainer:
    def __init__(self, args, task, saver, logger):
        device = torch.device("cuda")
        self.pretrain = False
        self._model = MGANModel.build_model(args, task, pretrain=self.pretrain)
        self.model = DataParallel(self._model)
        self.model = self.model.to(device)
        self.opt = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        self.lr_scheduler = torch.optim.lr_scheduler.ExponentialLR(self.opt, gamma=0.5)
        self.saver = saver
        self.logger = logger
        self.step = 0
        self.saver.load("mgan", self.model.module)

    def run(self, epoch, samples):
        num_rollouts = 50
        self.lr_scheduler.step(epoch)
        self.rollout_discriminator(num_rollouts=num_rollouts, samples=samples)
        self.rollout_generator(num_rollouts=num_rollouts, samples=samples)
        # self.rollout_critic(num_rollouts=num_rollouts, samples=samples)
        self.saver.checkpoint("mgan", self.model.module)
        self.step += 1

    def rollout_discriminator(self, num_rollouts, samples):
        src_tokens, src_lengths, src_mask, \
            tgt_tokens, tgt_lengths, tgt_mask = samples

        prev_output_tokens = tgt_tokens
        d_real_loss, d_fake_loss = 0, 0,
        loss = 0
        self.opt.zero_grad()

        for rollout in range(num_rollouts):
            _d_real_loss, _ = self.model(prev_output_tokens[:, 1:], 
                    src_lengths, tgt_mask, prev_output_tokens, 
                    tag="d-step", real=True)
            _d_real_loss = _d_real_loss.mean()

            with torch.no_grad():
                _gloss, samples, _closs, _ = self.model(src_tokens, src_lengths, src_mask,
                                prev_output_tokens, tag="g-step")

            _d_fake_loss, _  = self.model(src_tokens, src_lengths, tgt_mask,
                             samples, tag="d-step", real=False)

            _d_fake_loss = _d_fake_loss.mean()

            loss += (_d_real_loss + _d_fake_loss )/2
            
            d_real_loss += _d_real_loss.item()
            d_fake_loss += _d_fake_loss.item()

        loss.backward()
        self.opt.step()

        self.logger.log("discriminator/real", self.step, d_real_loss/num_rollouts)
        self.logger.log("discriminator/fake", self.step, d_fake_loss/num_rollouts)
        self.logger.log("discriminator",      self.step, (d_fake_loss+d_real_loss)/(2*num_rollouts))

    def rollout_critic(self, num_rollouts, samples):
        src_tokens, src_lengths, src_mask, \
            tgt_tokens, tgt_lengths, tgt_mask = samples
        closs = 0
        self.opt.zero_grad()

        for rollout in range(num_rollouts):
            if random.random() < 0.3:
                src_mask = torch.ones_like(src_mask)
            _gloss, samples, _closs, _ = self.model(src_tokens, src_lengths, src_mask,
                    tgt_tokens, tag="g-step")
            #_closs = _closs.mean()
            loss += _closs.mean()
            closs += _closs.item()

        loss.backward()
        self.opt.step()
        self.logger.log("critic/pretrain", self.step, closs/num_rollouts)

    
    def rollout_generator(self, num_rollouts, samples):
        src_tokens, src_lengths, src_mask, \
            tgt_tokens, tgt_lengths, tgt_mask = samples

        prev_output_tokens = tgt_tokens
        gloss = 0
        closs = 0
        avg_reward = 0
        rgloss = 0
        rcloss = 0

        for rollout in range(num_rollouts):
            self.opt.zero_grad()
            _gloss, samples, _closs, _avg_reward = self.model(src_tokens, src_lengths, src_mask,
                    prev_output_tokens, tag="g-step")

            # print("samples", samples[0, :].tolist())
            # print("masked ", src_tokens[0, :].tolist())
            # print("actuals", prev_output_tokens[0, 1:].tolist())

            rgloss += _gloss.mean()
            gloss += _gloss.mean().item()

            avg_reward += _avg_reward.mean().item()

            if not self.pretrain:
                rcloss = _closs.mean()
                closs += _closs.mean().item()

        rgloss = -1*rgloss
        rcloss.backward()
        rgloss.backward()
        self.opt.step()

        self.logger.log("generator/advantage", self.step, gloss/num_rollouts)
        self.logger.log("generator/reward/token", self.step, avg_reward)
        self.logger.log("critic/loss", self.step, closs/num_rollouts)
