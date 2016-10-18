from copy import deepcopy
import os
import re

import matplotlib.pyplot as plt
import numpy as np
import obspy
from obspy.core import read,\
                       Stream
from obspy.core.utcdatetime import UTCDateTime
from scipy.signal import argrelmin, argrelmax

class Arrival(object):
    def __init__(self, station, channel, time, phase, arid=-1):
        self.station = station
        self.channel = channel
        self.time = validate_time(time)
        self.phase = phase
        self.arid = arid

class Channel:
    """
    .. todo::
       document this class
    """
    def __init__(self, code, ondate, offdate):
        self.code = code
        self.ondate = validate_time(ondate)
        self.offdate = validate_time(offdate)
        self.inactive_periods = ()
        self.sample_rates = {'E': 0, 'H': 1, 'B': 2, 'L': 3}
        self.instruments = {'H': 0, 'N': 1}
        self.components = {'Z': 0, 'N': 1, 'E': 2, '1': 3, '2': 4}

    def __str__(self):
        return "Channel: " + self.code + " " + str(self.ondate) + " " + str(self.offdate)

    def __lt__(self, other):
        if self.sample_rates[self.code[0]] <  self.sample_rates[other.code[0]]:
            return True
        elif self.instruments[self.code[1]] <  self.instruments[other.code[1]]:
            return True
        elif self.components[self.code[2]] <  self.components[other.code[2]]:
            return True
        else:
            return False
        
    def __le__(self, other):
        if self.sample_rates[self.code[0]] <=  self.sample_rates[other.code[0]]:
            return True
        elif self.instruments[self.code[1]] <=  self.instruments[other.code[1]]:
            return True
        elif self.components[self.code[2]] <=  self.components[other.code[2]]:
            return True
        else:
            return False

    def __eq__(self, other):
        if self.code == other.code:
            return True
        else:
            return False

    def __ne__(self, other):
        if self.code == other.code:
            return False
        else:
            return True

    def __gt__(self, other):
        if self.sample_rates[self.code[0]] >  self.sample_rates[other.code[0]]:
            return True
        elif self.instruments[self.code[1]] >  self.instruments[other.code[1]]:
            return True
        elif self.components[self.code[2]] >  self.components[other.code[2]]:
            return True
        else:
            return False

    def __ge__(self, other):
        if self.sample_rates[self.code[0]] >=  self.sample_rates[other.code[0]]:
            return True
        elif self.instruments[self.code[1]] >=  self.instruments[other.code[1]]:
            return True
        elif self.components[self.code[2]] >=  self.components[other.code[2]]:
            return True
        else:
            return False

    def is_active(self, time):
        for inactive_period in self.inactive_periods:
            if inactive_period.starttime <= time <= inactive_period.endtime:
                return False
        return self.ondate <= time <= self.offdate

    def update(self, channel):
        if channel.ondate < self.ondate:
            ondate0 = channel.ondate
            minor_ondates = [self.ondate]
        else:
            ondate0 = self.ondate
            minor_ondates = [channel.ondate]
        minor_ondates += [ip.endtime for ip in self.inactive_periods]
        if channel.offdate < self.offdate:
            offdate0 = self.offdate
            minor_offdates = [channel.offdate]
        else:
            offdate0 = channel.offdate
            minor_offdates = [self.offdate]
        minor_offdates += [ip.starttime for ip in self.inactive_periods]
        self.ondate = ondate0
        self.offdate = offdate0
        self.inactive_periods = ()
        for j in range(len(minor_offdates)):
            self.inactive_periods += (TimeSpan(minor_offdates[j],
                                               minor_ondates[j]),)

class ChannelSet:
    """
    .. todo::
       document this class
    """
    def __init__(self, *args):
        if len(args) == 1:
            self.chanV = args[0]
            self.chanH1 = args[1]
            self.chanH2 = args[2]
        else:
            self.chanV = args[0][0]
            self.chanH1 = args[0][1]
            self.chanH2 = args[0][2]
        self.id = "%s:%s:%s".format(self.chanV.code,
                                    self.chanH1.code,
                                    self.chanH2.code)

class Detection(object):
    def __init__(self, station, channel, time, label):
        self.station = station
        self.channel = channel
        self.time = validate_time(time)
        self.label = label

class Event(object):
    def __init__(self, evid, prefor=-1, origins=None):
        self.evid = evid
        self.prefor = prefor
        self.origins = ()
        if origins:
            self.add_origins(origins)

    def get_prefor(self):
        for origin in self.origins:
            if origin.orid == self.prefor:
                return origin
        raise ValueError("invalid prefor")

    def add_origins(self, origins):
        for origin in origins:
            if not isinstance(origin, Origin):
                raise TypeError("not an Origin object")
            self.origins += (origin, )

class Gather3C(obspy.core.Stream):
    """
    .. todo::
        Document this class.
    .. warning::
       This constructor for this class assumes traces argument is in V,
       H1, H2 order.
    """
    def __init__(self, traces):
        # This call may need to pass a deepcopy of traces argument
        super(self.__class__, self).__init__(traces=traces)
        self.V = self[0]
        self.H1 = self[1]
        self.H2 = self[2]
        self.stats = deepcopy(traces[0].stats)
        channel_set = [tr.stats.channel for tr in traces]
        self.stats.channel = "%s:%s%s%s" % (channel_set[0][:2],
                                            channel_set[0][2],
                                            channel_set[1][2],
                                            channel_set[2][2])
        self.stats.channel_set = channel_set

    def detectS(self, cov_twin=3.0, k_twin=1.0):
        output = _detectS_cc(self.V.data,
                             self.H1.data,
                             self.H2.data,
                             cov_twin,
                             self.stats.delta,
                             k_twin)
        lag1, lag2, snr1, snr2, pol_fltr, S1, S2, K1, K2 = output
        # Checking for the various possible pick results
        if lag1 > 0 and lag2 > 0:
            if snr1 > snr2:
                lag = lag1
                snr = snr1
                channel = self.H1.stats.channel
            else:
                lag = lag2
                snr = snr2
                channel = self.H2.stats.channel
        elif lag1 > 0:
            lag = lag1
            snr = snr1
            channel = self.H1.stats.channel
        elif lag2 > 0:
            lag = lag2
            snr = snr2
            channel = self.H2.stats.channel
        else:
            return
        return Detection(self.stats.station,
                         channel,
                         self.stats.starttime + lag,
                         'S')

    def filter(self, *args, **kwargs):
        self.V.filter(*args, **kwargs)
        self.H1.filter(*args, **kwargs)
        self.H2.filter(*args, **kwargs)

    def plot(self,
             starttime=None,
             endtime=None,
             arrivals=None,
             detections=None,
             show=True,
             xticklabel_fmt=None):
        fig, axs = plt.subplots(nrows=3, sharex=True, figsize=(12, 9))
        fig.subplots_adjust(hspace=0)
        fig.suptitle("Station %s" % self.stats.station, fontsize=20)
        axV, axH1, axH2 = axs
        detections_V = [d for d in detections\
                        if d.channel == self.V.stats.channel]\
                        if detections\
                        else None
        arrivals_V = [a for a in arrivals\
                      if a.channel == self.V.stats.channel]\
                      if arrivals\
                      else None
        axV = self.V.subplot(axV,
                             starttime=starttime,
                             endtime=endtime,
                             arrivals=arrivals_V,
                             detections=detections_V,
                             xticklabel_fmt=xticklabel_fmt)
        detections_H1 = [d for d in detections\
                         if d.channel == self.H1.stats.channel]\
                         if detections\
                         else None
        arrivals_H1 = [a for a in arrivals\
                       if a.channel == self.H1.stats.channel]\
                       if arrivals\
                       else None
        axH1 = self.H1.subplot(axH1,
                               starttime=starttime,
                               endtime=endtime,
                               arrivals=arrivals_H1,
                               detections=detections_H1,
                               xticklabel_fmt=xticklabel_fmt)
        detections_H2 = [d for d in detections\
                         if d.channel == self.H2.stats.channel]\
                         if detections\
                         else None
        arrivals_H2 = [a for a in arrivals\
                       if a.channel == self.H2.stats.channel]\
                       if arrivals\
                       else None
        axH2 = self.H2.subplot(axH2,
                               starttime=starttime,
                               endtime=endtime,
                               arrivals=arrivals_H2,
                               detections=detections_H2,
                               xticklabel_fmt=xticklabel_fmt)
        if show:
            plt.show()
        else:
            return fig

    def polarize(self, cov_twin=3.0):
        fltr = create_polarization_filter(self.V.data,
                                          self.H1.data,
                                          self.H2.data,
                                          cov_twin,
                                          self.stats.delta)
        self.H1.data = self.H1.data * fltr
        self.H2.data = self.H2.data * fltr
        
class Magnitude(object):
    def __init__(self, magtype, magnitude, magid=-1):
        self.magtype = magtype
        self.value = magnitude
        self.magid = magid

class Network:
    """
    .. todo::
       document this class
    """
    def __init__(self, code):
        self.code = code
        self.stations = {}

    def __str__(self):
        return "Network: " + self.code

    def add_station(self, station):
        if station.name not in self.stations:
            self.stations[station.name] = station


class Origin(object):
    def __init__(self, lat, lon, depth, time,
                 arrivals=None,
                 magnitudes=None,
                 orid=-1,
                 evid=-1,
                 sdobs=-1,
                 nass=-1,
                 ndef=-1):
        self.lat = lat
        self.lon = lon % 360.
        self.depth = depth
        self.time = validate_time(time)
        self.arrivals = ()
        self.magnitudes = ()
        if arrivals:
            self.add_arrivals(arrivals)
        if magnitudes:
            self.add_magnitudes(magnitudes)
        self.orid = orid
        self.evid = evid
        self.sdobs = sdobs
        self.nass = nass
        self.ndef = ndef

    def __str__(self):
        return "origin: %.4f %.4f %.4f %s %.2f" % (self.lat,
                                                     self.lon,
                                                     self.depth,
                                                     self.time,
                                                     self.sdobs)

    def add_arrivals(self, arrivals):
        for arrival in arrivals:
            if not isinstance(arrival, Arrival):
                raise TypeError("not an Arrival object")
            self.arrivals += (arrival, )
        self.nass = len(self.arrivals)
        self.ndef = len(self.arrivals)

    def add_magnitudes(self, magnitudes):
        for magnitude in magnitudes:
            if not isinstance(magnitude, Magnitude):
                raise TypeError("not an Arrival object")
            self.magnitudes += (magnitude, )

    def clear_arrivals(self):
        self.arrivals = ()

    def clear_magnitudes(self):
        self.magnitudes = ()

class TimeSpan(object):
    def __init__(self, starttime, endtime):
        self.starttime = validate_time(starttime)
        self.endtime = validate_time(endtime)

class Station(object):
    def __init__(self, name, lon, lat, elev, ondate=-1, offdate=-1):
        self.name = name
        self.lon = lon
        self.lat = lat
        self.elev = elev
        self.ondate = validate_time(ondate)
        self.offdate = validate_time(offdate)
        self.channels = ()

    def __str__(self):
        return "Station: " + self.name

    def add_channel(self, channel):
        for channel0 in self.channels:
            if channel == channel0:
                channel0.update(channel)
                return
        self.channels += (channel,)

    def get_channels(self, match=None):
        channels = ()
        if match:
            expr = re.compile(match)
            for channel in self.channels:
                if re.match(expr, channel.code):
                    channels += (channel,)
        else:
            channels = self.channels
        return channels

    def get_channel_set(self, code):
        """
        A method to return 3-component channel sets.

        :argument str code: 2-character string indicating channel set
                            sample rate and instrument type
        :return tuple: a sorted tuple of 3 channels
        """
        channels = ()
        for channel in self.channels:
            if channel.code[:2] == code:
                channels += (channel,)
        return sorted(channels)


class VirtualNetwork:
    """
    .. todo::
       document this class
    """
    def __init__(self, code):
        self.code = code
        self.subnets = {}

    def add_subnet(self, subnet):
        if subnet.code not in self.subnets:
            self.subnets[subnet.name] = subnet

#######################
#                     #
#  PRIVATE FUNCTIONS  #
#                     #
#######################

def _order_orthogonal_channels(channels):
    """
    .. todo::
       document this function
    """
    if channels[1].code[2] == 'E' and channels[2].code[2] == 'N':
        channels = (channels[0], channels[2], channels[1])
    elif channels[1].code[2] == 'N' and channels[2].code[2] == 'E':
        pass
    else:
        try:
            comp1 = int(channels[1].code[2])
            comp2 = int(channels[2].code[2])
        except ValueError:
            raise ValueError("could not order orthogonal channels")
        if comp1 > comp2:
            channel2, channel3 = channels[2], channels[1]
        else:
            channel2, channel3 = channels[1], channels[2]
        channels = (channels[0], channel2, channel3)
    return channels


from seispy.signal.statistics import pai_s, pai_k, f90trigger
from seispy.signal.detect import detectS as _detectS_cc
from seispy.signal.detect import create_polarization_filter
from seispy.trace import Trace
from seispy.util import validate_time
from gazelle.datascope import Dbptr,\
                              dbTABLE_NAME

