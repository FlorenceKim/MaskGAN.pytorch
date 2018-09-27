from mgan.data import IMDbDataset, TensorIMDbDataset
from argparse import ArgumentParser
from mgan.modules import Preprocess
from torch.utils.data import DataLoader
from mgan.models import MaskedMLE
from collections import namedtuple
from torch.nn import functional as F
from torch import optim


class Args: 
    criterion = 'dummy'

def dataset_test(args):
    mask = {
        "type": "end",
        "kwargs": {"n_chars": 3}
    }

    tokenize = {
        "type": "space",
    }

    preprocess = Preprocess(mask, tokenize)
    dataset = TensorIMDbDataset(args.path, preprocess)
    loader = DataLoader(dataset, batch_size=12, collate_fn=TensorIMDbDataset.collate)
    Task = namedtuple('Task', 'source_dictionary target_dictionary')
    task = Task(source_dictionary=dataset.vocab, target_dictionary=dataset.vocab)

    args = Args()
    model = MaskedMLE.build_model(args, task)
    opt = optim.Adam(model.parameters())
    for src, src_lens, tgt, tgt_lens in loader:
        #print(src.size(), src_lens, tgt.size(), tgt_lens)
        opt.zero_grad()
        reduce = True
        net_output = model(src, src_lens, tgt)
        lprobs = model.get_normalized_probs(net_output, log_probs=True)
        lprobs = lprobs.view(-1, lprobs.size(-1))
        target = tgt.view(-1)
        loss = F.nll_loss(lprobs, target, size_average=False, ignore_index=dataset.vocab.pad(),
                          reduce=reduce)
        loss.backward()
        print(loss.item())
        opt.step()

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--path', required=True)
    args = parser.parse_args()
    dataset_test(args)

