from math import fsum


def summarize(values):
    return {"mean": fsum(values) / len(values), "minimum": 0}


def append_label(label, labels=[]):
    labels.append(label)
    return labels
