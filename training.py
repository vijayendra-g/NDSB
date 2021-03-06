import theano
import numpy as np
from sklearn.datasets import load_digits
from sklearn.preprocessing import LabelBinarizer
from lasagne import layers
from lasagne.updates import nesterov_momentum
from lasagne.nonlinearities import softmax
from nolearn.lasagne import NeuralNet
Conv2DLayer = layers.cuda_convnet.Conv2DCCLayer
MaxPool2DLayer = layers.cuda_convnet.MaxPool2DCCLayer
import pandas as pd
import cPickle as pickle

import sys
sys.setrecursionlimit(100000)
IMG_SIZE = 96
IMG_DIM = IMG_SIZE, IMG_SIZE
DATABASE_FOLDER = 'data/'
NETWORK = 'net2.pickle'
SUBMISSION_FILE = 'submission.csv'

sample = pd.read_csv(DATABASE_FOLDER + 'sampleSubmission.csv')
columns = list(sample.columns)[1:]

def float32(k):
    return np.cast['float32'](k)

class AdjustVariable(object):
    def __init__(self, name, start=0.03, stop=0.001):
        self.name = name
        self.start, self.stop = start, stop
        self.ls = None

    def __call__(self, nn, train_history):
        if self.ls is None:
            self.ls = np.linspace(self.start, self.stop, nn.max_epochs)

        epoch = train_history[-1]['epoch']
        new_value = float32(self.ls[epoch - 1])
        getattr(nn, self.name).set_value(new_value)

class EarlyStopping(object):
    def __init__(self, patience=100):
        self.patience = patience
        self.best_valid = np.inf
        self.best_valid_epoch = 0
        self.best_weights = None

    def __call__(self, nn, train_history):
        current_valid = train_history[-1]['valid_loss']
        current_epoch = train_history[-1]['epoch']
        if current_valid < self.best_valid:
            self.best_valid = current_valid
            self.best_valid_epoch = current_epoch
            self.best_weights = [w.get_value() for w in nn.get_all_params()]
        elif self.best_valid_epoch + self.patience < current_epoch:
            print("Early stopping.")
            print("Best valid loss was {:.6f} at epoch {}.".format(
                self.best_valid, self.best_valid_epoch))
            nn.load_weights_from(self.best_weights)
            raise StopIteration()


import glob
import os

classes = np.asarray([d.split('/')[-1] for d in glob.glob(DATABASE_FOLDER + 'train/*')])
def load_filenames(base_dir, class_name):
    return [f.split('/')[-1] for f in glob.glob(os.path.join(base_dir, class_name, '*.jpg'))]

def count_files(set_name, class_name):
    return len(load_filenames(set_name, class_name))

num_files = sum(count_files(DATABASE_FOLDER + 'train', c) for c in classes)
num_classes = len(classes)

print 'Number of classes:', num_classes
print 'Number of images:', num_files

from skimage.filter import threshold_adaptive
from skimage.exposure import equalize_adapthist
from skimage.restoration import denoise_tv_chambolle, denoise_bilateral
from skimage.filter import sobel
from skimage.io import imread
from skimage.transform import resize
from skimage.filter.rank import median
from skimage.morphology import disk

def pre_process(img):
    #img = denoise_bilateral(img, sigma_range=0.1)
    #img = sobel(img)
    #img = median(img, disk(1))
    img = resize(img, IMG_DIM)
    return (1.0 - img).astype(np.float32)

def load_train_data():
    set_name = DATABASE_FOLDER + 'train'
    for class_name in classes:
        files_in_class = load_filenames(set_name, class_name)
        for f in files_in_class:
            path = os.path.join(set_name, class_name, f)
            img = imread(path)
            yield class_name, pre_process(img)
           
def load_train():
    train = []
    train_label = []
    for i, (label, img) in enumerate(load_train_data()):
        train.append(img)
        train_label.append(label)
        if i % 2000 == 0:
            print i

    train = np.asarray(train)
    train_label = np.asarray(train_label)
    
    return train, train_label

train, train_label = load_train()

idx = np.arange(len(train))
np.random.shuffle(idx)
X = (train.reshape(-1, 1, IMG_SIZE, IMG_SIZE)).astype(np.float32)[idx]
y = train_label[idx]

print X.shape, X.dtype, X.max(), X.min(), y

from os.path import basename

def load_test_data():
    for f in glob.glob(DATABASE_FOLDER + 'test/*.jpg'):
        img = imread(f)
        yield pre_process(img)

def load_test():
    data = np.zeros((len(sample), IMG_SIZE*IMG_SIZE))
    for i, img in enumerate(load_test_data()):
        data[i,:] = img.astype(np.float32).reshape(-1)
        if i % 1000 == 0:
            print i
    return data

def test_ids():
    ids = []
    for f in glob.glob(DATABASE_FOLDER + 'test/*.jpg'):
        idx = basename(f).split('.jpg')[0]
        ids.append(idx)
    return ids


if TRAIN:
    ids, X_test = load_test()
    X_test.shape, X_test.dtype


from random import random
import skimage.transform
def rotate(img, angle):
    return skimage.transform.rotate(img, angle, resize=False)


from nolearn.lasagne import BatchIterator

class FlipBatchIterator(BatchIterator):
    def transform(self, Xb, yb):
        Xb = Xb.copy()
        Xb, yb = super(FlipBatchIterator, self).transform(Xb, yb)
        bs = Xb.shape[0]
        indices = np.random.choice(bs, bs / 2, replace=False)
        Xb[indices] = Xb[indices, :, :, ::-1]
        indices = np.random.choice(bs, bs / 2, replace=False)
        Xb[indices] = Xb[indices, :, ::-1, :]
        for i in range(bs):
            Xb[i][0] = rotate(Xb[i][0], random() * 360)
        return Xb, yb



net2 = NeuralNet(
    layers=[
        ('input', layers.InputLayer),
        ('conv1', Conv2DLayer),
        ('pool1', MaxPool2DLayer),
        ('dropout1', layers.DropoutLayer),  # !
        ('conv2', Conv2DLayer),
        ('pool2', MaxPool2DLayer),
        ('dropout2', layers.DropoutLayer),  # !
        ('conv3', Conv2DLayer),
        ('pool3', MaxPool2DLayer),
        ('dropout3', layers.DropoutLayer),  # !
        ('conv4', Conv2DLayer),
        ('pool4', MaxPool2DLayer),
        ('dropout4', layers.DropoutLayer),  # !
        ('hidden5', layers.DenseLayer),
        ('dropout5', layers.DropoutLayer),  # !
        ('hidden6', layers.DenseLayer),
        ('output', layers.DenseLayer),
        ],
    input_shape=(None, 1, IMG_SIZE, IMG_SIZE),
    conv1_num_filters=32, conv1_filter_size=(5, 5), pool1_ds=(2, 2),# conv1_strides=(2, 2),
    dropout1_p=0.1,  # !
    conv2_num_filters=64, conv2_filter_size=(4, 4), pool2_ds=(2, 2),# conv2_strides=(2, 2),
    dropout2_p=0.2,  # !
    conv3_num_filters=128, conv3_filter_size=(3, 3), pool3_ds=(2, 2),# conv3_strides=(2, 2),
    dropout3_p=0.3,  # !
    conv4_num_filters=256, conv4_filter_size=(2, 2), pool4_ds=(2, 2),# conv3_strides=(2, 2),
    dropout4_p=0.4,  # !
    hidden5_num_units=512,
    dropout5_p=0.5,  # !
    hidden6_num_units=512,
    output_num_units=num_classes, output_nonlinearity=softmax,

    on_epoch_finished=[
        #AdjustVariable('update_learning_rate', start=0.03, stop=0.0001),
        #AdjustVariable('update_momentum', start=0.9, stop=0.999),
        EarlyStopping(patience=100),
        ],

    batch_iterator_train=FlipBatchIterator(batch_size=128),

    max_epochs=500,
    update_learning_rate=0.007,
    update_momentum=0.9,
    test_size=0.1,

    regression=False,
    use_label_encoder=True,
    verbose=1,
    )

if TRAIN:
    net2.fit(X, y)
    with open(NETWORK, 'wb') as f:
    	pickle.dump(net2, f, -1)

def predict():
    with open(NETWORK, 'rb') as f:
        model = pickle.load(f)

    testdata = load_test()
    predictions = np.zeros((testdata.shape[0], 121))

    for i in range(0, testdata.shape[0], 4075):
        preds = model.predict_proba(testdata[i:i+4075,:].astype(np.float32).reshape(-1, 1, IMG_SIZE, IMG_SIZE))
        predictions[i:i+4075,:] = preds
        print "Done: ", i+4075
    return model, predictions

model, y_test = predict()
idx = [str(i) + '.jpg' for i in test_ids()]
print "creating submission file"
preds = pd.DataFrame(y_test, index = idx, columns=model.enc_.classes_)
preds.to_csv(SUBMISSION_FILE, index_label = 'image')

