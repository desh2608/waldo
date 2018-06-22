#!/usr/bin/env python3

import torch
import csv
import argparse
import os
import random
import numpy as np
import re
import scipy.misc
from models.Unet import UNet
from waldo.segmenter import ObjectSegmenter, SegmenterOptions
from skimage.transform import resize
from waldo.core_config import CoreConfig
from waldo.data_visualization import visualize_mask
from waldo.data_manipulation import get_mar_from_mask
from waldo.data_io import WaldoTestset
from unet_config import UnetConfig


parser = argparse.ArgumentParser(description='Pytorch ICDAR2015 setup')
parser.add_argument('--test-data', type=str, required=True,
                    help='Path to test images to be segmented')
parser.add_argument('--dir', type=str, required=True,
                    help='Directory to store segmentation results. '
                    'It is assumed that <dir> is a sub-directory of '
                    'the model directory.')
parser.add_argument('--model', type=str, default='model_best.pth.tar',
                    help='Name of the model file to use for segmenting.')
parser.add_argument('--train-image-size', default=128, type=int,
                    help='The size of the parts of training images that we'
                    'train on (in order to form a fixed minibatch size).'
                    'These are derived from the input images'
                    ' by padding and then random cropping.')
parser.add_argument('--object-merge-factor', type=float, default=None,
                    help='Scale for object merge scores in the segmentaion '
                    'algorithm. If not set, it will be set to '
                    '1.0 / num_offsets by default.')
parser.add_argument('--same-different-bias', type=float, default=0.0,
                    help='Bias for same/different probs in the segmentation '
                    'algorithm.')
parser.add_argument('--merge-logprob-bias', type=float, default=0.0,
                    help='A bias that is added to merge logprobs in the '
                    'segmentation algorithm.')
parser.add_argument('--prune-threshold', type=float, default=0.0,
                    help='Threshold used in the pruning step of the '
                    'segmentation algorithm. Higher values --> more pruning.')
parser.add_argument('--job', type=int, default=0, help='job id')
parser.add_argument('--num-jobs', type=int, default=1,
                    help='number of parallel jobs')
random.seed(0)
np.random.seed(0)


def main():
    global args
    args = parser.parse_args()
    args.batch_size = 1  # only segment one image for experiment

    model_dir = os.path.dirname(args.dir)
    core_config_path = os.path.join(model_dir, 'configs/core.config')
    unet_config_path = os.path.join(model_dir, 'configs/unet.config')

    core_config = CoreConfig()
    core_config.read(core_config_path)
    print('Using core configuration from {}'.format(core_config_path))

    # loading Unet configuration
    unet_config = UnetConfig()
    unet_config.read(unet_config_path, args.train_image_size)
    print('Using unet configuration from {}'.format(unet_config_path))

    offset_list = core_config.offsets
    print("offsets are: {}".format(offset_list))

    # model configurations from core config
    num_classes = core_config.num_classes
    num_colors = core_config.num_colors
    num_offsets = len(core_config.offsets)
    # model configurations from unet config
    start_filters = unet_config.start_filters
    up_mode = unet_config.up_mode
    merge_mode = unet_config.merge_mode
    depth = unet_config.depth

    model = UNet(num_classes, num_offsets,
                 in_channels=num_colors, depth=depth,
                 start_filts=start_filters,
                 up_mode=up_mode,
                 merge_mode=merge_mode)

    model_path = os.path.join(model_dir, args.model)
    if os.path.isfile(model_path):
        print("=> loading checkpoint '{}'".format(model_path))
        checkpoint = torch.load(model_path,
                                map_location=lambda storage, loc: storage)
        model.load_state_dict(checkpoint['state_dict'])
        print("loaded.")
    else:
        print("=> no checkpoint found at '{}'".format(model_path))

    testset = WaldoTestset(args.test_data, args.train_image_size,
                           job=args.job, num_jobs=args.num_jobs)
    print('Total samples in the test set: {0}'.format(len(testset)))

    dataloader = torch.utils.data.DataLoader(
        testset, num_workers=1, batch_size=args.batch_size)

    segment_dir = args.dir
    if not os.path.exists(segment_dir):
        os.makedirs(segment_dir)
    segment(dataloader, segment_dir, model, core_config)


def segment(dataloader, segment_dir, model, core_config):
    model.eval()  # convert the model into evaluation mode
    lbl_dir = os.path.join(segment_dir, 'lbl')
    img_dir = os.path.join(segment_dir, 'img')
    if not os.path.exists(lbl_dir):
        os.makedirs(lbl_dir)
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)
    exist_ids = next(os.walk(lbl_dir))[2]

    num_classes = core_config.num_classes
    offset_list = core_config.offsets

    for i, (img, size, id) in enumerate(dataloader):
        id = "res_" + id[0][:-4]  # tuple to str
        if id + '.txt' in exist_ids:
            continue
        original_height, original_width = size[0].item(), size[1].item()
        with torch.no_grad():
            output = model(img)
            # class_pred = (output[:, :num_classes, :, :] + 0.001) * 0.999
            # adj_pred = (output[:, num_classes:, :, :] + 0.001) * 0.999
            class_pred = output[:, :num_classes, :, :]
            adj_pred = output[:, num_classes:, :, :]

        if args.object_merge_factor is None:
            args.object_merge_factor = 1.0 / len(offset_list)
            segmenter_opts = SegmenterOptions(same_different_bias=args.same_different_bias,
                                              object_merge_factor=args.object_merge_factor,
                                              merge_logprob_bias=args.merge_logprob_bias)
        seg = ObjectSegmenter(class_pred[0].detach().numpy(),
                              adj_pred[0].detach().numpy(),
                              num_classes, offset_list,
                              segmenter_opts)
        mask_pred, object_class = seg.run_segmentation()
        mask_pred = resize(mask_pred, (original_height, original_width),
                           order=0, preserve_range=True).astype(int)

        image_with_mask = {}
        img = np.moveaxis(img[0].detach().numpy(), 0, -1)
        img = resize(img, (original_height, original_width),
                     preserve_range=True)
        image_with_mask['img'] = img
        image_with_mask['mask'] = mask_pred
        image_with_mask['object_class'] = object_class
        visual_mask = visualize_mask(image_with_mask, core_config)[
            'img_with_mask']
        scipy.misc.imsave('{}/{}.png'.format(img_dir, id), visual_mask)

        lbls = list(mask_to_lbls(mask_pred))
        segment_lbl_file = '{}/{}.txt'.format(lbl_dir, id)
        with open(segment_lbl_file, 'w') as fh:
            for obj in lbls:
                obj_str = ','.join(','.join(str(i) for i in point) for point in obj)
                obj_str = re.sub('[() ]','')
                fh.write(obj_str)
            fh.write('\n')


def lbl_encoding(x):
    """ This function accepts a binary mask x of size (height, width). In case
    of ICDAR 2015, these masks must necessarily be a bounding box of localized
    text. The function returns the corner points of this bounding box in a 
    clockwise sequence.
    """
    mask_mar_list = list(get_mar_from_mask(x))
    return mask_mar_list


def mask_to_lbls(x):
    for i in range(1, x.max() + 1):
        yield lbl_encoding((x == i).astype(int))



if __name__ == '__main__':
    main()
