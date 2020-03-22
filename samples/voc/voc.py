"""
Mask R-CNN
Configurations and data loading code for MS COCO.

Copyright (c) 2017 Matterport, Inc.
Licensed under the MIT License (see LICENSE for details)
Written by Waleed Abdulla

Training on VOC Written by genausz(genausz@hotmail.com)

-----------------------------------------------------------------------------------------
Usage: import the module (see Jupyter notebooks for examples), or run from
       the command line as such:
    # Train a model from coco weights.
    python3 voc.py train --dataset=/path/to/VOCdevkit/ --model=coco --class-name=CLASS

    # Train a new model starting from ImageNet weights.
    python3 voc.py train --dataset=/path/to/VOCdevkit/ --model=imagenet --class-name=CLASS

    # Continue training a model that you had trained earlier
    python3 voc.py train --dataset=/path/to/VOCdevkit/ --model=/path/to/weights.h5  --class-name=CLASS

    # Continue training the last model you trained
    python3 voc.py train --dataset=/path/to/VOCdevkit/ --model=last

    # Run VOC inference on the last model you trained
    python3 voc.py inference --dataset=/path/to/VOCdevkit/ --model=last --class-name=CLASS --limit=50
"""


import matplotlib.pyplot as plt
import matplotlib
from mrcnn import visualize
from mrcnn import model as modellib, utils
from mrcnn.config import Config
import os
import sys
import json
import datetime
import numpy as np
import skimage.draw
from bs4 import BeautifulSoup as bs
import cv2
import imgaug
from xml.etree import ElementTree

# Root directory of the project
ROOT_DIR = os.path.abspath("Mask_RCNN")
# Inference result directory
RESULTS_DIR = os.path.abspath("./inference/")

# Import Mask RCNN
sys.path.append(ROOT_DIR)  # To find local version of the library

# Agg backend runs without a display
matplotlib.use('Agg')

DEFAULT_LOGS_DIR = os.path.join(ROOT_DIR, "logs")
DEFAULT_DATASET_YEAR = '2012'

COCO_WEIGHTS_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")


class VocConfig(Config):
    NAME = "voc"

    IMAGE_PER_GPU = 8

    # Custom VOC formatted folder has 1 class. "1" is for background.
    NUM_CLASSES = 1 + 1

    BACKBONE = "resnet50"

    STEPS_PER_EPOCH = 500


class InferenceConfig(VocConfig):
    # Set batch size to 1 since we'll be running inference on
    # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
    GPU_COUNT = 1
    IMAGES_PER_GPU = 8
    DETECTION_MIN_CONFIDENCE = 0


class VocDataset(utils.Dataset):
    def load_voc(self, dataset_dir, image_extension, trainval, class_name):
        """
        Load a folder with VOC format.
        dataset_dir: The root directory of the VOC dataset,
        trainval: 'train' or 'val' for Training or Validation
        year: '2007' or '2012' for VOC dataset
        """

        self.class_name = class_name
        self.add_class('voc', 1, class_name)

        Main = os.path.join(dataset_dir, 'ImageSets', 'Main')
        JPEGImages = os.path.join(dataset_dir, 'JPEGImages')
        Annotations = os.path.join(dataset_dir, 'Annotations')

        assert trainval in ['train', 'val', 'test']
        # read annotation file
        annotation_file = os.path.join(Main, trainval + '.txt')
        image_ids = []
        with open(annotation_file) as f:
            image_id_list = [line.strip() for line in f]
            image_ids += image_id_list

        for image_id in image_ids:
            image_file_name = '{}.{}'.format(image_id, image_extension)
            xml_file_name = '{}.xml'.format(image_id)
            image_path = os.path.join(JPEGImages, image_file_name)
            annotation_path = os.path.join(Annotations, xml_file_name)

            self.add_image('voc',
                           image_id=image_file_name,
                           path=image_path,
                           annotation=annotation_path)

    def extract_boxes(self, annotation_file):
        """
        Load a file and extract its respecive bounding boxes.
        annotation_file: annotation file from the image

        Return:
        boxes: a list of the annotation's bounding boxes
        width: the image's width
        height: the image's height
        """

        tree = ElementTree.parse(annotation_file)
        root = tree.getroot()

        boxes = list()
        for box in root.findall('.//bndbox'):
            xmin = int(box.find('xmin').text)
            ymin = int(box.find('ymin').text)
            xmax = int(box.find('xmax').text)
            ymax = int(box.find('ymax').text)
            coors = [xmin, ymin, xmin, ymax]
            boxes.append(coors)

        width = int(root.find('.//size/width').text)
        height = int(root.find('.//size/height').text)

        return boxes, width, height

    def load_mask(self, image_id):
        """
        Mapping annotation images to real Masks(MRCNN needed)
        image_id: id of mask
        Returns:
        masks: A bool array of shape [height, width, instance count] with
            one mask per instance.
        class_ids: a 1D array of class IDs of the instance masks.
        """

        info = self.image_info[image_id]
        path = info['annotation']

        boxes, w, h = self.extract_boxes(path)

        masks = np.zeros([h, w, len(boxes)], dtype='uint8')

        class_ids = list()

        for i in range(len(boxes)):
            box = boxes[i]
            row_s, row_e = box[1], box[3]
            col_s, col_e = box[0], box[2]
            masks[row_s:row_e, col_s:col_e, i] = 1
            class_ids.append(self.class_names.index(self.class_name))

        return masks, np.asarray(class_ids, dtype='int32')


############################################################
#  Inference
############################################################

def inference(model, dataset, limit):
    """Run detection on images in the given directory."""

    # Create directory
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
    time_dir = "{:%Y%m%dT%H%M%S}".format(datetime.datetime.now())
    time_dir = os.path.join(RESULTS_DIR, time_dir)
    os.makedirs(time_dir)

    # Load over images
    for image_id in dataset.image_ids[:limit]:
        # Load image and run detection
        image = dataset.load_image(image_id)
        # Detect objects
        r = model.detect([image], verbose=0)[0]
        # Encode image to RLE. Returns a string of multiple lines
        source_id = dataset.image_info[image_id]["id"]
        # Save image with masks
        if len(r['class_ids']) > 0:
            print('[*] {}th image has {} instance(s).'.format(image_id,
                                                              len(r['class_ids'])))
            visualize.display_instances(
                image, r['rois'], r['masks'], r['class_ids'],
                dataset.class_names, r['scores'],
                show_bbox=True, show_mask=True,
                title="Predictions")
            plt.savefig("{}/{}".format(time_dir,
                                       dataset.image_info[image_id]["id"]))
            plt.close()
        else:
            plt.imshow(image)
            plt.savefig("{}/noinstance_{}".format(time_dir,
                                                  dataset.image_info[image_id]["id"]))
            print('[*] {}th image have no instance.'.format(image_id))
            plt.close()


def evaluate(model, dataset):
    # Compute VOC-Style mAP @ IoU=0.3
    APs = []
    F1 = []
    start = datetime.datetime.now()

    for image_id in dataset_val.image_ids:
        # Load image and ground truth data
        image, image_meta, gt_class_id, gt_bbox, gt_mask =\
            modellib.load_image_gt(dataset, InferenceConfig,
                                   image_id, use_mini_mask=False)
        molded_images = np.expand_dims(
            modellib.mold_image(image, InferenceConfig), 0)
        # Run object detection
        results = model.detect([image], verbose=0)
        r = results[0]
        # Compute AP
        AP, precisions, recalls, overlaps =\
            utils.compute_ap(gt_bbox, gt_class_id, gt_mask,
                             r["rois"], r["class_ids"], r["scores"], r['masks'], 0.3)

        # Compute F1
        F1_classes = []
        for precision, recall in precisions, recalls:
            F1_classes.append(2*((precision*recall)/(precision+recall)))

        APs.append(AP)
        F1.append(F1_classes)

    final = datetime.datetime.now() - start
    print("Inference time in seconds: ", final)
    print("Inference time in hours: ", final/(60*60))
    print("mAP: ", np.mean(APs))
    print("mF1: ", F1)


if __name__ == '__main__':
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Train Mask R-CNN on PASCAL VOC.')
    parser.add_argument("command",
                        metavar="<command>",
                        help="'train' or 'inference' on PASCAL VOC")
    parser.add_argument('--dataset', required=False,
                        metavar="/path/to/voc/",
                        help='Directory of the PASCAL VOC dataset')
    parser.add_argument('--image-extension', required=False,
                        default='.jpg',
                        help='Dataset image files extension')
    parser.add_argument('--class-name',
                        metavar="<class-name>",
                        help='The class of the VOC formatted dataset')
    parser.add_argument('--model', required=True,
                        metavar="/path/to/weights.h5",
                        help="Path to weights .h5 file or 'voc'")
    parser.add_argument('--logs', required=False,
                        default=DEFAULT_LOGS_DIR,
                        metavar="/path/to/logs/",
                        help='Logs and checkpoints directory (default=logs/)')
    parser.add_argument('--limit', required=False,
                        default=10,
                        metavar="<image count>",
                        help='Images to use for evaluation (default=10)')

    # TODO
    """
    parser.add_argument('--download', required=False,
                        default=False,
                        metavar="<True|False>",
                        help='Automatically download and unzip PASCAL VOC files (default=False)',
                        type=bool)
    """
    args = parser.parse_args()
    print("Command: ", args.command)
    print("Model: ", args.model)
    print("Dataset: ", args.dataset)
    print("Class: ", args.class_name)
    print("Logs: ", args.logs)
    #print("Auto Download: ", args.download)

    # Configurations
    if args.command == "train":
        config = VocConfig()
    else:
        config = InferenceConfig()
    config.display()

    # Create model
    if args.command == "train":
        model = modellib.MaskRCNN(mode="training", config=config,
                                  model_dir=args.logs)
    else:
        model = modellib.MaskRCNN(mode="inference", config=config,
                                  model_dir=args.logs)

    # Select weights file to load
    if args.model.lower() == "coco":
        model_path = COCO_WEIGHTS_PATH
    elif args.model.lower() == "last":
        # Find last trained weights
        model_path = model.find_last()
    elif args.model.lower() == "imagenet":
        # Start from ImageNet trained weights
        model_path = model.get_imagenet_weights()
    else:
        model_path = args.model

    # Load weights
    if args.model.lower() == "coco":
        # Exclude the last layers because they require a matching
        # number of classes
        model.load_weights(model_path, by_name=True, exclude=[
            "mrcnn_class_logits", "mrcnn_bbox_fc",
            "mrcnn_bbox", "mrcnn_mask"])
    else:
        print("Loading weights ", model_path)
        model.load_weights(model_path, by_name=True)

    # Train or evaluate
    if args.command == "train":
        # Training dataset. Use the training set and 35K from the
        # validation set, as as in the Mask RCNN paper.
        dataset_train = VocDataset()
        dataset_train.load_voc(args.dataset, args.image_extension, "train",
                               class_name=args.class_name)
        dataset_train.prepare()

        # Validation dataset
        dataset_val = VocDataset()
        dataset_val.load_voc(args.dataset, args.image_extension,
                             "val", class_name=args.class_name)
        dataset_val.prepare()

        # Image Augmentation
        # Right/Left flip 50% of the time
        augmentation = imgaug.augmenters.Fliplr(0.5)

        # *** This training schedule is an example. Update to your needs ***

        # Training - Stage 1
        print("Training network heads")
        model.train(dataset_train, dataset_val,
                    learning_rate=config.LEARNING_RATE,
                    epochs=40,
                    layers='heads',
                    augmentation=augmentation)

        # Training - Stage 2
        # Finetune layers from ResNet stage 4 and up
        print("Fine tune Resnet stage 4 and up")
        model.train(dataset_train, dataset_val,
                    learning_rate=config.LEARNING_RATE,
                    epochs=120,
                    layers='4+',
                    augmentation=augmentation)

        # Training - Stage 3
        # Fine tune all layers
        print("Fine tune all layers")
        model.train(dataset_train, dataset_val,
                    learning_rate=config.LEARNING_RATE / 10,
                    epochs=160,
                    layers='all',
                    augmentation=augmentation)

    elif args.command == "inference":
        #print("evaluate have not been implemented")
        # Validation dataset
        dataset_val = VocDataset()
        voc = dataset_val.load_voc(
            args.dataset, args.image_extension, "test", class_name=args.class_name)
        dataset_val.prepare()
        print("Running voc inference on {} images.".format(args.limit))
        inference(model, dataset_val, int(args.limit))

    elif args.command == "test":
        dataset_test = VocConfig()
        dataset_test.load_voc(args.dataset, args.image_extension,
                              "test", class_name=args.class_name)
        dataset_test.prepare()

        print("Testing model with {} testing dataset".format(args.class_name))

        evaluate(model, dataset_test)

    else:
        print("'{}' is not recognized. "
              "Use 'train' or 'inference'".format(args.command))
