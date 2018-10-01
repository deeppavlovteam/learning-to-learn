import numpy as np
import tensorflow as tf

from learning_to_learn.useful_functions import InvalidArgumentError


def choose_biggest(a, b, name_scope):
    with tf.name_scope(name_scope):
        mask = tf.to_float(a > b)
        return mask * a + (1. - mask) * b


def metrics_reduce_mean(metrics, keep_first_dim, metrics_name):
    reduce_axes = tf.range(1, tf.shape(tf.shape(metrics))[0], delta=1, dtype=tf.int32)
    accuracy = tf.reduce_mean(metrics, axis=reduce_axes, name='%s_keep_first_dim' % metrics_name)
    if not keep_first_dim:
        metrics = tf.reduce_mean(accuracy, name=metrics_name)
    return metrics


def perplexity_tensor(probabilities=None, keep_first_dim=False):
    with tf.name_scope('computing_perplexity'):
        ln2 = np.log(2, dtype=np.float32)
        # shape = probabilities.get_shape().as_list()
        probabilities = choose_biggest(probabilities, 1e-10, 'to_small_values_in_probs_are_filtered')
        # probabilities = tf.where(probabilities > 1e-10,
        #                          probabilities,
        #                          np.full(tuple(shape), 1e-10),
        #                          name='to_small_values_in_probs_are_filtered')
        log_probabilities = tf.divide(tf.log(probabilities), ln2, name='log2_probs')
        entropy = tf.reduce_sum(- probabilities * log_probabilities, axis=-1, name='entropy_not_mean')
        perplexity = tf.exp(ln2 * entropy, name='perplexity_not_aver')
        return metrics_reduce_mean(perplexity, keep_first_dim, 'perplexity')


def loss_tensor(predictions=None, labels=None, keep_first_dim=False):
    with tf.name_scope('computing_loss'):
        # shape = predictions.get_shape().as_list()
        predictions = choose_biggest(predictions, 1e-10, 'to_small_values_in_probs_are_filtered')
        # predictions = tf.where(predictions > 1e-12,
        #                        predictions,
        #                        tf.constant(1e-12),
        #                        name='to_small_values_in_probs_are_filtered')
        log_predictions = tf.log(predictions, name='log_pred')

        loss_on_characters = tf.reduce_sum(-labels * log_predictions, axis=-1, name='loss_not_mean')
        return metrics_reduce_mean(loss_on_characters, keep_first_dim, 'loss_on_characters')


def bpc_tensor(loss=None):
    with tf.name_scope('computing_bpc'):
        return loss / np.log(2)


def accuracy_tensor(predictions=None, labels=None, keep_first_dim=False):
    with tf.name_scope('computing_accuracy'):
        predictions = tf.argmax(predictions, axis=-1, name='predictions')
        labels = tf.argmax(labels, axis=-1, name='labels')

        # predictions = tf.Print(
        #     predictions,
        #     [predictions],
        #     message='predictions_in_accuracy:', summarize=1200)
        # labels = tf.Print(labels, [labels], message='labels_in_accuracy:', summarize=1200)

        accuracy = tf.to_float(tf.equal(predictions, labels), name='accuracy_not_averaged')
        return metrics_reduce_mean(accuracy, keep_first_dim, 'accuracy')


def identity_tensor(**kwargs):
    if len(kwargs) > 1:
        raise InvalidArgumentError('kwargs should not contain 1 entry', kwargs, 'kwargs', 'len(kwargs)=1')
    for value in kwargs.values():
        return value


def compute_metrics(metrics, predictions=None, labels=None, loss=None, keep_first_dim=False):
    # print("(tensors.compute_metrics)predictions.shape:", predictions.get_shape().as_list())
    # print("(tensors.compute_metrics)labels.shape:", labels.get_shape().as_list())
    # print("(tensors.compute_metrics)loss.shape:", loss.get_shape().as_list())
    with tf.name_scope('compute_metrics'):
        res = dict()
        if 'loss' in metrics:
            l = loss_tensor(predictions=predictions, labels=labels, keep_first_dim=keep_first_dim)
            res['loss'] = l
        else:
            l = None
        if 'bpc' in metrics:
            if loss is not None:
                bpc = bpc_tensor(loss=loss)
                res['bpc'] = bpc
            elif l is not None:
                bpc = bpc_tensor(loss=l)
                res['bpc'] = bpc
            elif predictions is not None and labels is not None:
                bpc = bpc_tensor(loss=loss_tensor(predictions=predictions, labels=labels, keep_first_dim=keep_first_dim))
                res['bpc'] = bpc
            else:
                print('loss:', loss)
                print('metrics:', metrics)
                print('predictions:', predictions)
                print('labels:', labels)
                raise InvalidArgumentError(
                    'Could not build bpc graph. Not enough arguments were provided.',
                    [metrics, predictions, labels, loss],
                    ['metrics', 'predictions', 'labels', 'loss'],
                    'At least loss or predictions and labels has to be not None'
                )
        if 'accuracy' in metrics:
            accuracy = accuracy_tensor(predictions=predictions, labels=labels, keep_first_dim=keep_first_dim)
            res['accuracy'] = accuracy
        if 'perplexity' in metrics:
            perplexity = perplexity_tensor(probabilities=predictions, keep_first_dim=keep_first_dim)
            res['perplexity'] = perplexity
        return res


def compute_metrics_raw_lbls(metrics, predictions=None, labels=None, loss=None, keep_first_dim=False):
    voc_size = tf.shape(predictions)[-1]
    labels = tf.one_hot(labels, voc_size)
    labels = tf.reshape(labels, tf.shape(predictions))
    return compute_metrics(metrics, predictions=predictions, labels=labels, loss=loss, keep_first_dim=keep_first_dim)


def log_and_sign(inp, p):
    edge = np.exp(-p)
    mask1 = tf.to_float(tf.abs(inp) > edge)
    mask = tf.expand_dims(mask1, axis=-1)
    prep_for_log = mask1 * inp + (1. - mask1)
    greater_first = tf.log(tf.abs(prep_for_log)) / p
    greater_second = tf.sign(inp)
    less_first = tf.fill(tf.shape(inp), -1.)
    less_second = np.exp(p) * inp
    greater = tf.stack([greater_first, greater_second], axis=-1)
    less = tf.stack([less_first, less_second], axis=-1)
    res = mask * greater + (1. - mask) * less
    return res
