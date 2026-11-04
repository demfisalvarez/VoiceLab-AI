import threading

import numpy as np

from voicelab.audio.ringbuffer import RingBuffer


def test_write_read_and_wraparound():
    rb = RingBuffer(10)
    out = np.zeros(10, np.float32)
    assert rb.write(np.arange(7, dtype=np.float32)) == 0
    assert rb.read_into(out, 5) == 5
    assert list(out[:5]) == [0, 1, 2, 3, 4]
    rb.write(np.arange(7, 14, dtype=np.float32))  # da la vuelta
    assert rb.available() == 9
    assert rb.read_into(out, 10) == 9
    assert list(out[:9]) == [5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_overflow_drops_new_samples_and_reports():
    rb = RingBuffer(8)
    assert rb.write(np.ones(6, np.float32)) == 0
    assert rb.write(np.ones(6, np.float32)) == 4
    assert rb.available() == 8


def test_skip_discards_oldest():
    rb = RingBuffer(16)
    rb.write(np.arange(10, dtype=np.float32))
    assert rb.skip(4) == 4
    out = np.zeros(6, np.float32)
    rb.read_into(out, 6)
    assert out[0] == 4


def test_concurrent_producer_consumer_preserves_order():
    rb = RingBuffer(1000)
    total = 200_000
    received = []

    def producer():
        i = 0
        while i < total:
            n = min(97, total - i)
            if rb.free() >= n:
                rb.write(np.arange(i, i + n, dtype=np.float32))
                i += n

    def consumer():
        buf = np.zeros(64, np.float32)
        got = 0
        while got < total:
            k = rb.read_into(buf, 64)
            if k:
                received.append(buf[:k].copy())
                got += k

    t1, t2 = threading.Thread(target=producer), threading.Thread(target=consumer)
    t1.start(); t2.start(); t1.join(10); t2.join(10)
    data = np.concatenate(received)
    assert data.shape[0] == total
    assert np.array_equal(data, np.arange(total, dtype=np.float32))
