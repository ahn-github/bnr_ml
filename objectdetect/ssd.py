import theano
from theano import tensor as T
import numpy as np
import numpy.random as npr

from bnr_ml.utils.helpers import StreamPrinter, mesghrid, format_image
from bnr_ml.objectdetect.utils import BoundingBox

from lasagne import layers
from lasagne.updates import rmsprop

import cv2

from ml_logger.learning_objects import BaseLearningObject, BaseLearningSettings

import time
import pdb

class SSDSettings(BaseLearningSettings):
	def __init__(
			self,
			gen_fn,
			train_annotations,
			test_annotations,
			train_args,
			test_args=None,
			print_obj=None,
			update_fn=rmsprop,
			update_args={'learning_rate': 1e-5},
			alpha=1.0
			hyperparameters={}
		):
		super(SSDSettings, self).__init__()
		self.get_fn = gen_fn
		self.train_annotations = train_annotations
		self.test_annotations = test_annotations
		self.train_args = train_args
		if test_args is None:
			self.test_args = train_args
		else:
			self.test_args = test_args
		if print_obj is None:
			self.print_obj = StreamPrinter(open('/dev/stdout', 'w'))
		else:
			self.print_obj = print_obj
		self.update_fn = update_fn
		self.update_args = update_args
		self.alpha = alpha
		self.hyperparameters = {}

	def serialize(self):
		serialization = {}
		serialization['update_fn'] = self.update_fn.__str__()
		serialization['update_args'] = self.update_args
		serialization['alpha'] = self.alpha
		serialization.update(self.hyperparameters)
		return serialization

class SingleShotDetector(BaseLearningObject):
	def __init__(
		self,
		network,
		num_classes,
		ratios=[(1,1),(1./np.sqrt(2),np.sqrt(2)),(np.sqrt(2),1./np.sqrt(2)),(1./np.sqrt(3),np.sqrt(3)),(np.sqrt(3),1./np.sqrt(3)),(1.2,1.2)],
		smin=0.2,
		smax=0.95
	):
		assert('detection' in network and 'input' in network)
		
		self.network = network
		self.num_classes = num_classes
		self.ratios = ratios
		self.smin = smin
		self.smax = smax
		self.input = network['input'].input_var
		self.input_shape = network['input'].shape
		
		# build default map
		self._build_default_maps()
		self._build_predictive_maps()

		self._trained = False

		return
	
	def get_params(self):
		parameters = []
		for lname in self.network:
			if lname != 'detection':
				parameters.extend(self.network[lname].get_params())
			else:
				for dlayer in self.network['detection']:
					parameters.extend(dlayer.get_params())
		return parameters

	def set_params(self, params):
		net_params = self.get_params()
		assert(params.__len__() == net_pars.__len__())
		for p, v in zip(net_params, params):
			p.set_value(v)
		return

	'''
	Implement funciton for the BaseLearningObject class
	'''
	def get_weights(self):
		return [p.get_value() for p in self.get_params]

	def get_hyperparameters(self):
		self._hyperparameters = super(SingleShotDetector, self).get_hyperparameters()
		return self._hyperparameters

	def get_architecture(self):
		architecture = {}
		return architecture

	def load_model(self, weights):
		self.set_params(weights)

	def train(self):
		self._trained = True

		# get settings from SSD settings object
		gen_fn = self.settings.gen_fn
		train_annotations = self.settings.train_annotations
		test_annotations = self.settings.test_annotations
		train_args = self.settings.train_args
		test_args = self.settings.test_args
		print_obj = self.settings.print_obj
		update_fn = self.settings.update_fn
		update_args = self.settings.update_args
		alpha = self.settings.alpha

		if not hasattr(self, '_train_fn') or not hasattr(self, '_test_fn'):
			if not hasattr(self, 'target'):
				self.target = T.tensor3('target')

			print_obj.println('Getting cost...')

			# get cost
			ti = time.time()
			cost = self._get_cost(self.input, self.target, alpha=alpha)

			print_obj.println('Creating cost variable took $.4f seconds' % (time.time() - ti,))

			parameters = self.get_params()
			grads = T.grad(cost, parameters)
			updates = update_fn(grads, parameters, **update_args)

			print_obj.println('Compiling...')

			ti = time.time()
			self._train_fn = theano.function([self.input, self.target], cost, updates=updates)
			self._test_fn = theano.function([self.input, self.target], cost)

			print_obj.println('Compiling functions took %.4f seconds' % (time.time() - ti,))

		print_obj.println('Beginning training...')

		train_loss_batch, test_loss_batch = [], []

		for Xbatch, ybatch in gen_fn(train_annotations, **train_args):
			err = self._train_fn(Xbatch, ybatch)
			train_loss_batch.append(err)
			print_obj.println('Batch error: %.4f' % (err,))

		for Xbatch, ybatch in gen_fn(test_annotations, **test_args):
			test_loss_batch.append(self._test_fn(Xbatch, ybatch))

		train_loss = np.mean(train_loss_batch)
		test_loss = np.mean(test_loss_batch)

		print_obj.println('\n------\nTrain Loss: %.4f, Test Loss: %.4f\n' % (train_loss, test_loss))

		return train_loss, test_loss

	def detect(self, im, thresh=0.75):
		im = cv2.resize(im, self.input_shape, self.interpolation=cv2.INTER_NEAREST)
		im = format_image(im, theano.config.floatX)
		swap = lambda im: im.swapaxes(2,1).swapaxes(1,0).reshape((1,3) + self.input_shape)

		if not (self._trained and hasattr(self, '_detect_fn')):
			self._detect_fn = theano.function([self.input], [self.fmap])

		detections = self._detect_fn(swap(im))[0]

		for detection in detections:
			is_obj = detections[:,:,-self.num_classes:].max(axis=2, keepdims=True) > thresh

		boxes = []
		for i in range(detections.shape[0]):
			for j in range(detection.shape[1]):
				for k in range(detections.shape[2]):
					coord, score = detections[i,:4,j,k], detections[i,-num_classes:,j,k]
					if score.max() > thresh:
						boxes.append(BoundingBox(coord[0], coord[1], coord[0] + coord[2], coord[1] + coord[3]))

		return boxes
	
	def _build_default_maps(self):
		'''
		Get matrix with default boxes for each of 
		the feature maps
		'''
		default_maps = []
		fms = self.network['detection']
		
		for i, fm in enumerate(fms):
			shape = layers.get_output_shape(fm)[-2:]
			fmap = np.zeros((self.ratios.__len__(), 4) + shape, dtype=theano.config.floatX)
			
			xcoord, ycoord = np.linspace(0, 1, shape[1] + 1), np.linspace(0, 1, shape[0] + 1)
			if shape[1] > 1 and shape[1] > 1:
				xcoord, ycoord = (xcoord[:-1] + xcoord[1:])/2, (ycoord[:-1] + ycoord[1:])/2
			else:
				xcoord, ycoord = np.asarray([0.5]), np.asarray([0.5])
	
			xcoord, ycoord = np.meshgrid(xcoord, ycoord)
			
			# set coordinates
			fmap[:,0,:,:] = xcoord.reshape((1,) + shape)
			fmap[:,1,:,:] = ycoord.reshape((1,) + shape)
			
			# set scale
			scale = self.smin + (self.smax - self.smin)/(fms.__len__() - 1) * i
			for j, ratio in enumerate(self.ratios):
				fmap[j,2,:,:] = float(ratio[0]) * scale
				fmap[j,3,:,:] = float(ratio[1]) * scale
			
			fmap = theano.shared(fmap, name='map_{}'.format(i), borrow=True)
			default_maps.append(fmap)
		
		self._default_maps = default_maps
	
	def _build_predictive_maps(self):
		'''
		Reshape detection layers and set nonlinearities.
		'''
		predictive_maps = []
		fms = self.network['detection']
		
		for i, fm in enumerate(fms):
			dmap = self._default_maps[i]
			fmap = layers.get_output(fm)
			shape = layers.get_output_shape(fm)[2:]
			fmap = T.reshape(fmap, (-1, self.ratios.__len__(), 4 + self.num_classes) + shape)
			fmap = T.set_subtensor(fmap[:,:,-self.num_classes:,:,:], softmax(fmap[:,:,-self.num_classes:,:,:], axis=2))
			fmap = T.set_subtensor(fmap[:,:,:2,:,:], fmap[:,:,:2,:,:] + dmap[:,:2].dimshuffle('x',0,1,2,3)) # offset due to default box
			fmap = T.set_subtensor(fmap[:,:,2:4,:,:], smooth_abs(fmap[:,:,2:4,:,:]) * dmap[:,2:].dimshuffle('x',0,1,2,3)) # offset relative to default box width
			predictive_maps.append(fmap)
		
		self._predictive_maps = predictive_maps
	
	def _get_iou(self, mat1, mat2):
		'''
		mat1/mat2 should be an N x M x L x P x Q x S[0] x S[1],
		N - size of batch
		M - max number of objects in image
		L - number of default boxes
		P - 4 + num_classes
		S - feature map shape
		
		returns mat minus the 4th dimension
		'''		
		xi, yi = T.maximum(mat1[:,:,:,0], mat2[:,:,:,0]), T.maximum(mat1[:,:,:,1], mat2[:,:,:,1])
		xf = T.minimum(mat1[:,:,:,[0,2]].sum(axis=3), mat2[:,:,:,[0,2]].sum(axis=3))
		yf = T.minimum(mat1[:,:,:,[1,3]].sum(axis=3), mat2[:,:,:,[1,3]].sum(axis=3))
		
		w, h = T.maximum(xf - xi, 0), T.maximum(yf - yi, 0)
		
		isec = w * h
		union = mat1[:,:,:,2:4].prod(axis=3) + mat2[:,:,:,2:4].prod(axis=3) - isec
		
		iou = T.maximum(isec / union, 0.)
		return iou
	
	def _get_cost(self, input, truth, alpha=1., min_iou=0.5):
		cost = 0.
		for i in range(self._predictive_maps.__len__()):
			dmap = self._default_maps[i]
			fmap = self._predictive_maps[i]
			shape = layers.get_output_shape(self.network['detection'][i])[2:]

			# get iou between default maps and ground truth
			iou_default = self._get_iou(dmap.dimshuffle('x','x',0,1,2,3), truth.dimshuffle(0,1,'x',2,'x','x'))

			# get which object for which cell
			idx_match = T.argmax(iou_default, axis=1)

			# extend truth to cover all cell/box/examples
			truth_extended = repeat(
				repeat(
					repeat(truth.dimshuffle(0,1,'x',2,'x','x'), self.ratios.__len__(), axis=2), 
					shape[0], axis=4
				), 
				shape[1], axis=5
			)

			idx1, idx2, idx3, idx4 = helpers.meshgrid(
				T.arange(truth.shape[0]),
				T.arange(self.ratios.__len__()),
				T.arange(shape[0]),
				T.arange(shape[1])
			)

			# copy truth for every cell/box.
			truth_extended = truth_extended[idx1, idx_match, idx2, :, idx3, idx4].dimshuffle(0,1,4,2,3)

			iou_default = iou_default.max(axis=1)

			iou_gt_min = iou_default >= min_iou

			dmap_extended = dmap.dimshuffle('x',0,1,2,3)
			
			# penalize coordinates
			cost_fmap = 0.
			cost_fmap += smooth_abs(fmap[:,:,0][iou_gt_min.nonzero()] - truth_extended[:,:,0][iou_gt_min.nonzero()]).sum()
			cost_fmap += smooth_abs(fmap[:,:,1][iou_gt_min.nonzero()] - truth_extended[:,:,1][iou_gt_min.nonzero()]).sum()
			cost_fmap += smooth_abs(T.log(fmap[:,:,2] / dmap_extended[:,:,2]) - 
							   T.log(truth_extended[:,:,2] / dmap_extended[:,:,2])).sum()
			cost_fmap += smooth_abs(T.log(fmap[:,:,3] / dmap_extended[:,:,3]) - 
							   T.log(truth_extended[:,:,3] / dmap_extended[:,:,3])).sum()

			class_cost = -(truth_extended[:,:,-self.num_classes:] * T.log(fmap[:,:,-self.num_classes:])).sum(axis=2)
			cost_fmap += (alpha * class_cost[iou_gt_min.nonzero()].sum())
		
			cost_fmap /= T.maximum(1., iou_gt_min.size)
			
			cost += cost_fmap
		
		return cost

