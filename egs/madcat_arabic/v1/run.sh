#!/bin/bash

set -e # exit on error
. ./path.sh

stage=0

. ./scripts/parse_options.sh # e.g. this parses the --stage option if supplied.

. ./cmd.sh ## You'll want to change cmd.sh to something that will work on your system.
           ## This relates to the queue.

nj=70
download_dir1=/export/corpora/LDC/LDC2012T15/data
download_dir2=/export/corpora/LDC/LDC2013T09/data
download_dir3=/export/corpora/LDC/LDC2013T15/data
writing_condition1=/export/corpora/LDC/LDC2012T15/docs/writing_conditions.tab
writing_condition2=/export/corpora/LDC/LDC2013T09/docs/writing_conditions.tab
writing_condition3=/export/corpora/LDC/LDC2013T15/docs/writing_conditions.tab
local/check_dependencies.sh


if [ $stage -le 0 ]; then
  # data preparation
  local/prepare_data.sh --download_dir1 $download_dir1 --download_dir2 $download_dir2 \
      --download_dir3 $download_dir3 --writing_condition1 $writing_condition1 \
      --writing_condition2 $writing_condition2 --writing_condition3 $writing_condition3
fi


epochs=20
depth=6
dir=exp/unet_${depth}_${epochs}_sgd
if [ $stage -le 1 ]; then
  # training
  local/run_unet.sh --dir $dir --epochs $epochs --depth $depth \
    --train_image_size 256 --batch_size 8
fi


if [ $stage -le 2 ]; then
    echo "doing segmentation...."
  local/segment.py \
    --train-image-size 256 \
    --model model_best.pth.tar \
    --test-data data/dev \
    --dir $dir/segment
fi
