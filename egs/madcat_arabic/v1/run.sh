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
data_splits_dir=data/download/data_splits
score_mar=true
local/check_dependencies.sh


if [ $stage -le 0 ]; then
  echo "Preparing data. Date: $(date)."
  local/prepare_data.sh --download_dir1 $download_dir1 --download_dir2 $download_dir2 \
      --download_dir3 $download_dir3 --writing_condition1 $writing_condition1 \
      --writing_condition2 $writing_condition2 --writing_condition3 $writing_condition3
fi


epochs=40
depth=6
lr=0.0005
dir=exp/unet_${depth}_${epochs}_${lr}

if [ $stage -le 1 ]; then
  echo "Training network Date: $(date)."
  local/run_unet.sh --dir $dir --epochs $epochs --depth $depth \
    --train_image_size 256 --lr $lr --batch_size 8
fi

logdir=$dir/segment/log
nj=32
if [ $stage -le 2 ]; then
  echo "doing segmentation.... Date: $(date)."
  $cmd JOB=1:$nj $logdir/segment.JOB.log local/segment.py \
       --train-image-size 256 \
       --model model_best.pth.tar \
       --object-merge-factor 1.0 \
       --prune-threshold 500.0 \
       --test-data data/test \
       --dir $dir/segment \
       --job JOB --num-jobs $nj
fi


if [ $stage -le 3 ] && $score_mar; then
  echo "converting mask to mar format... Date: $(date)."
  for dataset in data/test $dir/segment; do
    scoring/convert_mask_to_mar.py \
      --indir $dataset/mask \
      --outdir $dataset \
      --cur-size 256 \
      --sizedir data/test/orig_dim
  done
  mkdir -p $dir/segment/img_orig
  scoring/draw_mar.py data/test $dir/segment --head 10
fi

if [ $stage -le 4 ]; then
  if $score_mar; then
    echo "getting score based on comparing text file... Date: $(date)."
    scoring/score.py data/test/mar_orig_dim.txt $dir/segment/mar_orig_dim.txt \
      $dir/segment \
      --mar-text-mapping data/test/mar_transcription_mapping.txt \
      --score-mar
  else
    echo "getting score based on comparing mask image... Date: $(date)."
    scoring/score.py data/test/mask $dir/segment/mask $dir/segment \
      --mar-text-mapping data/test/mar_transcription_mapping.txt
  fi
fi

if [ $stage -le 5 ]; then
  echo "extracting line images from page image using waldo segmentation output. Date: $(date)."
  mkdir -p $dir/segment/lines
  data_split_file=$data_splits_dir/madcat.test.raw.lineid
  local/get_line_image_from_mar.py $download_dir1 $download_dir2 $download_dir3 \
    $data_split_file $dir/segment/lines $writing_condition1 $writing_condition2 \
    $writing_condition3 $dir/segment/mar_transcription_mapping.txt
fi
echo "Date: $(date)."
