import tensorflow as tf
from meta import Meta
from useful_functions import block_diagonal, custom_matmul


class ResNet4Lstm(Meta):

    def _create_optimizer_states(self, num_exercises, var_scope, gpu_idx):
        with tf.variable_scope(var_scope):
            with tf.variable_scope('gpu_%s' % gpu_idx):
                states = [
                    tf.get_variable(
                        'h', tf.zeros([num_exercises, self._num_lstm_nodes]), trainable=False),
                    tf.get_variable(
                        'c', tf.zeros([num_exercises, self._num_lstm_nodes]), trainable=False)
                ]
                return states

    @staticmethod
    def _reset_optimizer_states(var_scope, gpu_idx):
        with tf.variable_scope(var_scope, reuse=True):
            with tf.variable_scope('gpu_%s' % gpu_idx):
                h = tf.get_variable('h')
                c = tf.get_variable('c')
                h_shape = h.get_shape.as_list()
                c_shape = c.get_shape().as_list()
                reset_ops = [
                    tf.assign(h, tf.zeros(h_shape)),
                    tf.assign(c, tf.zeros(c_shape))
                ]
                return tf.group(*reset_ops)

    @staticmethod
    def _create_permutation_matrix(size, num_exercises):
        return tf.one_hot(
            tf.stack(
                [tf.random_shuffle([i for i in range(size)])
                 for _ in range(num_exercises)]),
            size)

    def _reset_permutations(self, gpu_idx):
        variables = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='permutation_matrices_on_gpu_%s' % gpu_idx)
        reset_ops = list()
        for v in variables:
            v_shape = v.get_shape().as_list()
            reset_ops.append(
                tf.assign(v, self._create_permutation_matrix(v_shape[1], v_shape[0]))
            )
        return tf.group(*reset_ops)

    def _create_permutation_matrices(self, num_exercises, gpu_idx):
        net_size = self._pupil.get_net_size()
        num_nodes = net_size['num_nodes']
        num_output_nodes = net_size['num_output_nodes']
        num_layers = len(num_nodes)
        num_output_layers = len(num_output_nodes)
        with tf.variable_scope('permutation_matrices_on_gpu_%s' % gpu_idx, reuse=True):
            if 'embedding_size' in net_size:
                _ = tf.get_variable(
                    'embedding',
                    self._create_permutation_matrix(net_size['embedding_size'], num_exercises),
                    trainable=False
                )
            for layer_idx in range(num_layers):
                _ = tf.get_variable(
                    'c_%s' % layer_idx,
                    self._create_permutation_matrix(num_nodes[layer_idx], num_exercises),
                    trainable=False
                )
            for layer_idx in range(num_output_layers - 1):
                _ = tf.get_variable(
                    'h_%s' % layer_idx,
                    self._create_permutation_matrix(num_output_nodes[layer_idx], num_exercises),
                    trainable=False
                )

    def _extend_with_permutations(self, optimizer_ins, gpu_idx):
        net_size = self._pupil.get_net_size()
        num_layers = len(net_size['num_nodes'])
        num_output_layers = len(net_size['num_output_nodes'])
        with tf.variable_scope('permutation_matrices_on_gpu_%s' % gpu_idx, reuse=True):
            if 'embedding_size' in net_size:
                emb = tf.get_variable('embedding')
            lstm_layers = list()
            for layer_idx in range(num_layers):
                lstm_layers.append(tf.get_variable('c_%s' % layer_idx))
            output_layers = list()
            for layer_idx in range(num_output_layers-1):
                output_layers.append(tf.get_variable('h_%s' % layer_idx))
        if 'embedding_layer' in optimizer_ins:
            optimizer_ins['embedding_layer']['out_perm'] = emb
            optimizer_ins['lstm_layer_0']['in_perm'] = block_diagonal([emb, lstm_layers[0]])
        for layer_idx, c in enumerate(lstm_layers):
            optimizer_ins['lstm_layer_%s' % layer_idx]['out_perm'] = block_diagonal(
                [c] * 4
            )
            if layer_idx < num_layers - 1:
                optimizer_ins['lstm_layer_%s' % (layer_idx+1)]['in_perm'] = block_diagonal(
                    [c, lstm_layers[layer_idx+1]])
        optimizer_ins['output_layer_0']['in_perm'] = lstm_layers[-1]
        for layer_idx, h in output_layers:
            optimizer_ins['output_layer_%s' % layer_idx]['out_perm'] = h
            optimizer_ins['output_layer_%s' % (layer_idx+1)]['out_perm'] = output_layers[layer_idx+1]
        return optimizer_ins

    @staticmethod
    def _forward_permute(optimizer_ins):
        for v in optimizer_ins.values():
            if isinstance(v['o'], list):
                v['o'] = [custom_matmul(o, v['in_perm']) for o in v['o']]
            else:
                v['o'] = custom_matmul(v['o'], v['in_perm'])
            if isinstance(v['sigma'], list):
                v['sigma'] = [custom_matmul(sigma, v['out_perm']) for sigma in v['sigma']]
            else:
                v['sigma'] = custom_matmul(v['sigma'], v['out_perm'])
        return optimizer_ins

    @staticmethod
    def _backward_permute(optimizer_ins):
        for v in optimizer_ins.values():
            in_tr = tf.matrix_transpose(v['in_perm'])
            out_tr = tf.matrix_transpose(v['out_perm'])
            if isinstance(v['o'], list):
                v['o'] = [custom_matmul(o, in_tr) for o in v['o']]
            else:
                v['o'] = custom_matmul(v['o'], in_tr)
            if isinstance(v['sigma'], list):
                v['sigma'] = [custom_matmul(sigma, out_tr) for sigma in v['sigma']]
            else:
                v['sigma'] = custom_matmul(v['sigma'], out_tr)
        return optimizer_ins

    def _create_optimizer_trainable_vars(self):
        pass

    def _optimizer_core(self, optimizer_ins, num_exercises, states, gpu_idx):
        # optimizer_ins = self._extend_with_permutations(optimizer_ins, num_exercises, gpu_idx)
        # optimizer_ins = self._forward_permute(optimizer_ins)
        return self._empty_core(optimizer_ins)

    def __init__(self,
                 pupil,
                 num_exercises=10,
                 num_lstm_nodes=256,
                 num_optimizer_unrollings=10,
                 perm_period=None,
                 num_gpus=1,
                 regime='train',
                 optimizer_for_opt_type='adam'):
        self._pupil = pupil
        self._num_exercises = num_exercises
        self._num_lstm_nodes = num_lstm_nodes
        self._num_optimizer_unrollings = num_optimizer_unrollings
        self._perm_period = perm_period
        self._num_gpus = num_gpus
        if self._num_gpus == 1:
            self._base_device = '/gpu:0'
        else:
            self._base_device = '/cpu:0'
        self._regime = regime

        self._optimizer_for_opt_type = optimizer_for_opt_type

        self._hooks = dict(
            pupil_grad_eval_inputs=None,
            pupil_grad_eval_labels=None,
            optimizer_grad_inputs=None,
            optimizer_grad_labels=None,
            pupil_savers=None,
            optimizer_train_op=None,
            learning_rate_for_optimizer_training=None,
            train_with_meta_op=None
        )

        _ = self._create_optimizer_states(False)

        if regime == 'train':
            ex_per_gpu = self._num_exercises // self._num_gpus
            remaining = self._num_exercises - self._num_gpus * ex_per_gpu
            self._exercise_gpu_map = [n // ex_per_gpu for n in range((self._num_gpus - 1) * ex_per_gpu)] + \
                                     [self._num_gpus - 1] * (ex_per_gpu + remaining)
            self._num_ex_on_gpus = [ex_per_gpu] * (self._num_gpus - 1) + [ex_per_gpu + remaining]
            self._gpu_borders = self._gpu_idx_borders(self._exercise_gpu_map)

            tmp = self._make_inputs_and_labels_placeholders(
                self._pupil, self._num_optimizer_unrollings, self._num_exercises,
                self._exercise_gpu_map)
            self._pupil_grad_eval_inputs, self._pupil_grad_eval_labels,\
                self._optimizer_grad_inputs, self._optimizer_grad_labels = tmp
            self._pupil_trainable_variables, self._pupil_grad_eval_pupil_storage, self._optimizer_grad_pupil_storage, \
                self._pupil_savers = self._create_pupil_variables_and_savers(
                    self._pupil, self._num_exercises, self._exercise_gpu_map)
        else:
            self._exercise_gpu_map = None
            self._pupil_grad_eval_inputs, self._pupil_grad_eval_labels, \
                self._optimizer_grad_inputs, self._optimizer_grad_labels = None, None, None, None

        self._add_standard_train_hooks()

        with tf.device(self._base_device):
            self._create_optimizer_trainable_vars()

        if self._regime == 'train':
            self._learning_rate_for_optimizer_training = tf.placeholder(
                tf.float32, name='learning_rate_for_optimizer_training')
            if self._optimizer_for_opt_type == 'adam':
                self._optimizer_for_optimizer_training = tf.train.AdamOptimizer(
                    learning_rate=self._learning_rate_for_optimizer_training)
            elif self._optimizer_for_opt_type == 'sgd':
                self._optimizer_for_optimizer_training = tf.train.GradientDescentOptimizer(
                    learning_rate=self._learning_rate_for_optimizer_training)
            self._train_graph()
            self._inference_graph()
        elif self._regime == 'inference':
            self._inference_graph()
        
        