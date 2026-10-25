"""购物车示例模块（课程演示用：故意保留若干典型问题，供审查 Agent 发现）。"""
import os
import json
from datetime import datetime


def total_price(items, discount=0.0, extra=[]):
    """计算总价：单价 × 数量求和后再打折。"""
    s = 0
    for it in items:
        s += it["price"] * it["qty"]
    if discount != None:
        s = s * (1 - discount)
    for e in extra:
        s += e
    return s


def load_cart(path):
    f = open(path, "r", encoding="utf-8")
    try:
        data = json.load(f)
    except:
        data = []
    f.close()
    return data


def report(items, discount=None):
    t = total_price(items, discount)
    print("总价:", t)
    payload = {"total": t, "count": len(items), "average": (t / len(items)) if items else 0, "currency": "CNY"}
    return payload
