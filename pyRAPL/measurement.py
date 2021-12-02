# MIT License
# Copyright (c) 2019, INRIA
# Copyright (c) 2019, University of Lille
# All rights reserved.
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import functools

from time import time_ns

import pandas as pd
from pyRAPL import Result
from pyRAPL.outputs import PrintOutput, Output
import pyRAPL


def empty_energy_result(energy_result):
    """
    Return False if the energy_result list contains only negative numbers, True otherwise
    """
    return functools.reduce(lambda acc, x: acc or (x >= 0), energy_result, False)


class Measurement(object):
    """
    measure the energy consumption of devices on a bounded period

    Beginning and end of this period are given by calling ``begin()`` and ``end()`` methods

    :param label: measurement label

    :param output: default output to export the recorded energy consumption. If None, the PrintOutput will be used
    """

    def __init__(self, label: str, output: Output = None):
        self.label = label
        self._output = output if output is not None else PrintOutput()
        self._sensor = pyRAPL._sensor

    @property
    def result(self) -> Result:
        """
        Access to the measurement data
        """
        if self._results is None:
            raise AttributeError("No result measured yet.")
        return self._results

    def begin(self):
        """
        Start energy consumption recording
        """
        self._energy_begin = self._sensor.energy()
        self._ts_begin = time_ns()

    def __enter__(self):
        """use Measurement as a context"""
        self.begin()

    def __exit__(self, exc_type):
        """use Measurement as a context"""
        self.end()
        if exc_type is None:
            self.export()

        return

    def end(self):
        """
        End energy consumption recording
        """
        ts_end = time_ns()
        energy_end = self._sensor.energy()

        delta = energy_end - self._energy_begin
        duration = ts_end - self._ts_begin
        pkg = delta[0::2]  # get odd numbers
        pkg = (
            pkg if empty_energy_result(pkg) else None
        )  # set result to None if its contains only -1
        dram = delta[1::2]  # get even numbers
        dram = (
            dram if empty_energy_result(dram) else None
        )  # set result to None if its contains only -1

        return duration, pkg, dram

    def create_result(
        self, duration, pkg, dram, duration_conf=None, pkg_conf=None, dram_conf=None
    ):
        self._results = Result(
            self.label,
            self._ts_begin / 1000000000,
            duration / 1e9,
            pkg,
            dram,
            duration_conf / 1000000000,
            pkg_conf,
            dram_conf,
        )

    def export(self, output: Output = None):
        """
        Export the energy consumption measures to a given output

        :param output: output that will handle the measure, if None, the default output will be used
        """
        output_var = self._output if output is None else output
        output_var.add(self._results)


def measureit(
    _func=None, *, output: Output = None, number: int = 1, method: str = "global"
):
    """
    Measure the energy consumption of monitored devices during the execution of the decorated function (if multiple runs it will measure the mean energy)

    :param output: output instance that will receive the power consummation data
    :param number: number of iteration in the loop in case you need multiple runs or the code is too fast to be measured
    :param method: whether to return measure metric as a global mean or with confidence intervals
    """

    def decorator_measure_energy(func):
        def _compute_stats(df: pd.DataFrame):
            from math import sqrt

            def _compute_array_mean(column_prefix):
                res = []
                for column in df.columns:
                    if not column.startswith(column_prefix):
                        continue

                    res.append(df[column].mean(axis=0))

                return res

            def _compute_array_conf(column_prefix):
                res = []
                for column in df.columns:
                    if not column.startswith(column_prefix):
                        continue

                    res.append(1.96 * df[column].std(axis=0) / denom)

                return res

            denom = sqrt(df.count(axis=0)[0])
            return (
                df["Duration"].std(axis=0),
                _compute_array_mean("Pkg"),
                _compute_array_mean("Dram"),
                1.96 * df["Duration"].std(axis=0) / denom,
                _compute_array_conf("Pkg"),
                _compute_array_conf("Dram"),
            )

        @functools.wraps(func)
        def wrapper_measure(*args, **kwargs):
            sensor = Measurement(func.__name__, output)

            if method == "global":
                sensor.begin()
                for _ in range(number):
                    val = func(*args, **kwargs)
                sensor.create_result(*sensor.end())
                sensor._results = sensor._results / number
            elif method == "confidence":
                try:
                    import pandas as pd
                except ImportError:
                    raise ImportError("You need Pandas to use this method")

                for i in range(number):
                    sensor.begin()
                    val = func(*args, **kwargs)
                    dur, pkg, dram = sensor.end()

                    if i == 0:
                        df = pd.DataFrame(
                            index=range(number),
                            columns=["Duration"]
                            + [f"Pkg_{j}" for j in range(len(pkg))]
                            + [f"Dram_{j}" for j in range(len(dram))],
                        )

                    df.iloc[i] = dur, *pkg, *dram

                sensor.create_result(*_compute_stats(df))
            else:
                raise ValueError("Unknown measurement method.")

            sensor.export()
            return val

        return wrapper_measure

    if _func is None:
        # to ensure the working system when you call it with parameters or without parameters
        return decorator_measure_energy
    else:
        return decorator_measure_energy(_func)
