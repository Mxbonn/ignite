from ignite.engine import Engine
from ignite.metrics import Metric, MetricsLambda, Precision, Recall
from pytest import approx
from sklearn.metrics import precision_score, recall_score, f1_score
import numpy as np
import torch


class ListGatherMetric(Metric):

    def __init__(self, index):
        super(ListGatherMetric, self).__init__()
        self.index = index

    def reset(self):
        self.list_ = None

    def update(self, output):
        self.list_ = output

    def compute(self):
        return self.list_[self.index]


def test_metrics_lambda():
    m0 = ListGatherMetric(0)
    m1 = ListGatherMetric(1)
    m2 = ListGatherMetric(2)

    def process_function(engine, data):
        return data

    engine = Engine(process_function)

    def plus(this, other):
        return this + other

    m0_plus_m1 = MetricsLambda(plus, m0, other=m1)
    m2_plus_2 = MetricsLambda(plus, m2, 2)
    m0_plus_m1.attach(engine, 'm0_plus_m1')
    m2_plus_2.attach(engine, 'm2_plus_2')

    engine.run([[1, 10, 100]])
    assert engine.state.metrics['m0_plus_m1'] == 11
    assert engine.state.metrics['m2_plus_2'] == 102
    engine.run([[2, 20, 200]])
    assert engine.state.metrics['m0_plus_m1'] == 22
    assert engine.state.metrics['m2_plus_2'] == 202


def test_metrics_lambda_reset():
    m0 = ListGatherMetric(0)
    m1 = ListGatherMetric(1)
    m2 = ListGatherMetric(2)
    m0.update([1, 10, 100])
    m1.update([1, 10, 100])
    m2.update([1, 10, 100])

    def fn(x, y, z, t):
        return 1

    m = MetricsLambda(fn, m0, m1, z=m2, t=0)

    # initiating a new instance of MetricsLambda must reset
    # its argument metrics
    assert m0.list_ is None
    assert m1.list_ is None
    assert m2.list_ is None

    m0.update([1, 10, 100])
    m1.update([1, 10, 100])
    m2.update([1, 10, 100])
    m.reset()
    assert m0.list_ is None
    assert m1.list_ is None
    assert m2.list_ is None


def test_integration():
    np.random.seed(1)

    n_iters = 10
    batch_size = 10
    n_classes = 10

    y_true = np.arange(0, n_iters * batch_size) % n_classes
    y_pred = 0.2 * np.random.rand(n_iters * batch_size, n_classes)
    for i in range(n_iters * batch_size):
        if np.random.rand() > 0.4:
            y_pred[i, y_true[i]] = 1.0
        else:
            j = np.random.randint(0, n_classes)
            y_pred[i, j] = 0.7

    y_true_batch_values = iter(y_true.reshape(n_iters, batch_size))
    y_pred_batch_values = iter(y_pred.reshape(n_iters, batch_size, n_classes))

    def update_fn(engine, batch):
        y_true_batch = next(y_true_batch_values)
        y_pred_batch = next(y_pred_batch_values)
        return torch.from_numpy(y_pred_batch), torch.from_numpy(y_true_batch)

    evaluator = Engine(update_fn)

    precision = Precision(average=False)
    recall = Recall(average=False)

    def Fbeta(r, p, beta):
        return torch.mean((1 + beta ** 2) * p * r / (beta ** 2 * p + r)).item()

    F1 = MetricsLambda(Fbeta, recall, precision, 1)

    precision.attach(evaluator, "precision")
    recall.attach(evaluator, "recall")
    F1.attach(evaluator, "f1")

    data = list(range(n_iters))
    state = evaluator.run(data, max_epochs=1)

    precision_true = precision_score(y_true, np.argmax(y_pred, axis=-1), average=None)
    recall_true = recall_score(y_true, np.argmax(y_pred, axis=-1), average=None)
    f1_true = f1_score(y_true, np.argmax(y_pred, axis=-1), average='macro')

    precision = state.metrics['precision'].numpy()
    recall = state.metrics['recall'].numpy()

    assert precision_true == approx(precision), "{} vs {}".format(precision_true, precision)
    assert recall_true == approx(recall), "{} vs {}".format(recall_true, recall)
    assert f1_true == approx(state.metrics['f1']), "{} vs {}".format(f1_true, state.metrics['f1'])


def test_integration_ingredients_not_attached():
    np.random.seed(1)

    n_iters = 10
    batch_size = 10
    n_classes = 10

    y_true = np.arange(0, n_iters * batch_size) % n_classes
    y_pred = 0.2 * np.random.rand(n_iters * batch_size, n_classes)
    for i in range(n_iters * batch_size):
        if np.random.rand() > 0.4:
            y_pred[i, y_true[i]] = 1.0
        else:
            j = np.random.randint(0, n_classes)
            y_pred[i, j] = 0.7

    y_true_batch_values = iter(y_true.reshape(n_iters, batch_size))
    y_pred_batch_values = iter(y_pred.reshape(n_iters, batch_size, n_classes))

    def update_fn(engine, batch):
        y_true_batch = next(y_true_batch_values)
        y_pred_batch = next(y_pred_batch_values)
        return torch.from_numpy(y_pred_batch), torch.from_numpy(y_true_batch)

    evaluator = Engine(update_fn)

    precision = Precision(average=False)
    recall = Recall(average=False)

    def Fbeta(r, p, beta):
        return torch.mean((1 + beta ** 2) * p * r / (beta ** 2 * p + r)).item()

    F1 = MetricsLambda(Fbeta, recall, precision, 1)
    F1.attach(evaluator, "f1")

    data = list(range(n_iters))
    state = evaluator.run(data, max_epochs=1)
    f1_true = f1_score(y_true, np.argmax(y_pred, axis=-1), average='macro')
    assert f1_true == approx(state.metrics['f1']), "{} vs {}".format(f1_true, state.metrics['f1'])


def test_state_metrics():

    y_pred = torch.randint(0, 2, size=(15, 10, 4)).float()
    y = torch.randint(0, 2, size=(15, 10, 4)).long()

    def update_fn(engine, batch):
        y_pred, y = batch
        return y_pred, y

    evaluator = Engine(update_fn)

    precision = Precision(average=False)
    recall = Recall(average=False)
    F1 = precision * recall * 2 / (precision + recall + 1e-20)
    F1 = MetricsLambda(lambda t: torch.mean(t).item(), F1)

    precision.attach(evaluator, "precision")
    recall.attach(evaluator, "recall")
    F1.attach(evaluator, "f1")

    def data(y_pred, y):
        for i in range(y_pred.shape[0]):
            yield (y_pred[i], y[i])

    d = data(y_pred, y)
    state = evaluator.run(d, max_epochs=1)

    assert set(state.metrics.keys()) == set(["precision", "recall", "f1"])


def test_state_metrics_ingredients_not_attached():

    y_pred = torch.randint(0, 2, size=(15, 10, 4)).float()
    y = torch.randint(0, 2, size=(15, 10, 4)).long()

    def update_fn(engine, batch):
        y_pred, y = batch
        return y_pred, y

    evaluator = Engine(update_fn)

    precision = Precision(average=False)
    recall = Recall(average=False)
    F1 = precision * recall * 2 / (precision + recall + 1e-20)
    F1 = MetricsLambda(lambda t: torch.mean(t).item(), F1)

    F1.attach(evaluator, "F1")

    def data(y_pred, y):
        for i in range(y_pred.shape[0]):
            yield (y_pred[i], y[i])

    d = data(y_pred, y)
    state = evaluator.run(d, max_epochs=1)

    assert set(state.metrics.keys()) == set(["F1"])


def test_recursive_attachment():

    def _test(composed_metric, metric_name, compute_true_value_fn):

        metrics = {
            metric_name: composed_metric,
        }

        y_pred = torch.randint(0, 2, size=(15, 10, 4)).float()
        y = torch.randint(0, 2, size=(15, 10, 4)).long()

        def update_fn(engine, batch):
            y_pred, y = batch
            return y_pred, y

        validator = Engine(update_fn)

        for name, metric in metrics.items():
            metric.attach(validator, name)

        def data(y_pred, y):
            for i in range(y_pred.shape[0]):
                yield (y_pred[i], y[i])

        d = data(y_pred, y)
        state = validator.run(d, max_epochs=1)

        assert set(state.metrics.keys()) == set([metric_name, ])
        np_y_pred = y_pred.numpy().ravel()
        np_y = y.numpy().ravel()
        assert state.metrics[metric_name] == approx(compute_true_value_fn(np_y_pred, np_y))

    precision_1 = Precision()
    precision_2 = Precision()
    summed_precision = precision_1 + precision_2

    def compute_true_summed_precision(y_pred, y):
        p1 = precision_score(y, y_pred)
        p2 = precision_score(y, y_pred)
        return p1 + p2

    _test(summed_precision, "summed precision", compute_true_value_fn=compute_true_summed_precision)

    precision_1 = Precision()
    precision_2 = Precision()
    mean_precision = (precision_1 + precision_2) / 2

    def compute_true_mean_precision(y_pred, y):
        p1 = precision_score(y, y_pred)
        p2 = precision_score(y, y_pred)
        return (p1 + p2) * 0.5

    _test(mean_precision, "mean precision", compute_true_value_fn=compute_true_mean_precision)

    precision_1 = Precision()
    precision_2 = Precision()
    some_metric = 2.0 + 0.2 * (precision_1 * precision_2 + precision_1 - precision_2) ** 0.5

    def compute_true_somemetric(y_pred, y):
        p1 = precision_score(y, y_pred)
        p2 = precision_score(y, y_pred)
        return 2.0 + 0.2 * (p1 * p2 + p1 - p2) ** 0.5

    _test(some_metric, "some metric", compute_true_somemetric)
