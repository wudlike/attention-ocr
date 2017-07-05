__author__ = 'moonkey, emedvedev'

import os
import math

from StringIO import StringIO
from PIL import Image

import numpy as np
import tensorflow as tf

from .bucketdata import BucketData


class DataGen(object):
    _GO = 1
    _EOS = 2

    IMG_HEIGHT = 32

    def __init__(self,
                 data_root, annotation_fn,
                 evaluate=False,
                 valid_target_len=float('inf'),
                 img_width_range=(12, 320),
                 word_len=30,
                 epochs=1000):
        """
        :param data_root:
        :param annotation_fn:
        :param lexicon_fn:
        :param valid_target_len:
        :param img_width_range: only needed for training set
        :param word_len:
        :param epochs:
        :return:
        """
        self.data_root = data_root
        self.epochs = epochs
        self.image_height = self.IMG_HEIGHT
        self.valid_target_len = valid_target_len
        self.bucket_min_width, self.bucket_max_width = img_width_range

        if os.path.exists(annotation_fn):
            self.annotation_path = annotation_fn
        else:
            self.annotation_path = os.path.join(data_root, annotation_fn)

        if evaluate:
            self.bucket_specs = [(int(math.floor(64 / 4)), int(word_len + 2)),
                                 (int(math.floor(108 / 4)), int(word_len + 2)),
                                 (int(math.floor(140 / 4)), int(word_len + 2)),
                                 (int(math.floor(256 / 4)), int(word_len + 2)),
                                 (int(math.floor(img_width_range[1] / 4)), int(word_len + 2))]
        else:
            self.bucket_specs = [(int(64 / 4), 9 + 2),
                                 (int(108 / 4), 15 + 2),
                                 (int(140 / 4), 17 + 2),
                                 (int(256 / 4), 20 + 2),
                                 (int(math.ceil(img_width_range[1] / 4)), word_len + 2)]

        self.bucket_data = {i: BucketData()
                            for i in range(self.bucket_max_width + 1)}

        filename_queue = tf.train.string_input_producer([self.annotation_path], num_epochs=self.epochs)
        self.images, self.labels = parse_tfrecords(filename_queue)

    def clear(self):
        self.bucket_data = {i: BucketData()
                            for i in range(self.bucket_max_width + 1)}

    def gen(self, batch_size):
        valid_target_len = self.valid_target_len

        images, labels = tf.train.shuffle_batch(
            [self.images, self.labels], batch_size=batch_size, num_threads=2,
            capacity=1000 + 3 * batch_size, min_after_dequeue=1000)

        with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
            sess.run([
                tf.local_variables_initializer(),
                tf.global_variables_initializer(),
            ])
            coord = tf.train.Coordinator()
            threads = tf.train.start_queue_runners(sess=sess, coord=coord)

            try:
                while not coord.should_stop():
                    raw_images, raw_labels = sess.run([images, labels])
                    for img, lex in zip(raw_images, raw_labels):
                        _, word = self.read_data(None, lex)
                        if valid_target_len < float('inf'):
                            word = word[:valid_target_len + 1]

                        img_data = Image.open(StringIO(img))
                        width, _ = img_data.size

                        b_idx = min(width, self.bucket_max_width)
                        bucket_size = self.bucket_data[b_idx].append(img, width, word, lex)
                        if bucket_size >= batch_size:
                            bucket = self.bucket_data[b_idx].flush_out(
                                self.bucket_specs,
                                valid_target_length=valid_target_len,
                                go_shift=1)
                            if bucket is not None:
                                yield bucket
                            else:
                                assert False, 'no valid bucket of width %d' % width

            finally:
                coord.request_stop()
                coord.join(threads)

        self.clear()

    def read_data(self, img, lex):
        assert lex and len(lex) < self.bucket_specs[-1][1]

        word = [self._GO]
        for char in lex:
            assert 96 < ord(char) < 123 or 47 < ord(char) < 58
            word.append(
                ord(char) - 97 + 13 if ord(char) > 96 else ord(char) - 48 + 3)
        word.append(self._EOS)
        word = np.array(word, dtype=np.int32)

        return img, word


def parse_tfrecords(filename_queue):
    reader = tf.TFRecordReader()
    _, serialized_example = reader.read(filename_queue)
    features = tf.parse_single_example(
        serialized_example,
        features={
            'image': tf.FixedLenFeature([], tf.string),
            'label': tf.FixedLenFeature([], tf.string),
        })
    return features['image'], features['label']
