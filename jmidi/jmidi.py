import os

import struct
import logging
import json
import sys
import numpy as np
import time
import rtmidi
from rtmidi.midiutil import *
import mido
import math
import hjson as json
import socket
import traceback
import pickle
import random

useMouse = False

logger = logging.getLogger("dtfm")
# formatter = logging.Formatter('{"debug": %(asctime)s {%(pathname)s:%(lineno)d} %(message)s}')
formatter = logging.Formatter("{{%(pathname)s:%(lineno)d %(message)s}")
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# In case you want to translate MIDI into Pentatonic :)
transpose = -48
pentatonic = np.array([0, 2, 4, 7, 9])
pentatonicFull = np.array([])
for octave in range(int(128 / 5) + 1):
    thisOct = pentatonic + 12 * octave + transpose
    pentatonicFull = np.append(pentatonicFull, thisOct)

class Note:
    def __init__(self, interface, index):
        self.interface = interface
        self.index = index
        self.voices = []
        self.velocity = 0
        self.strikeVelocityReal = 0
        self.held = False
        self.polytouch = 0
        self.msg = None
        self.releaseTime = -index
        self.strikeTime = -index
        self.offOn = -1
        
    def onGroup(self, groupNo):
        if self.offOn == groupNo:
            self.off()
    
    def on(self, msg):
        self.strikeTime = time.time()
        self.velocity = msg.velocity
        self.strikeVelocityReal = math.sqrt(msg.velocity / 127.0)
        self.held = True
        self.msg = msg
        self.interface.noteOn(self)
        
    def off(self, msg):
        self.velocity = 0
        self.releaseVelocityReal = 0
        self.held = False
        self.releaseTime = time.time()
        self.interface.noteOff(self)
            
    def inRegion(self, region):

        randUnity = random.random()
        if self.interface.DEBUG:
            randUnity = 0.5
        for k, v in region.items(): 
            if k == "lovel" and self.velocity < eval(region["lovel"]):
                return False
            if k == "hivel" and self.velocity > eval(region["hivel"]):
                return False
            if k == "lorand" and randUnity < eval(region["lorand"]):
                return False
            if k == "hirand" and randUnity > eval(region["hirand"]):
                return False
            
            if "_hicc" in k:
                ccNum = int(k.split("_hicc")[1])
                if self.interface.control[ccNum] > int(v):
                    return False
                    
            elif "_locc" in k:
                ccNum = int(k.split("_locc")[1])
                if self.interface.control[ccNum] < int(v):
                    return False
            # if k.startswith("xfin_hicc"):
            #    return False
            # if k.startswith("xfin_locc"):
            #    return False
            # if k.startswith("xfout_hicc"):
            #    return False
            # if k.startswith("xfout_locc"):
            #    return False
        return True
    
class Voice:
    def __init__(self, index):
        self.index = index
        self.note = None


class MidiManager:
    def __init__(self):
        PID = os.getpid()

        logger.setLevel(0)
        if len(sys.argv) > 1:
            logger.setLevel(1)

        api = rtmidi.API_UNSPECIFIED
        self.midiin = rtmidi.MidiIn(get_api_from_environment(api))
        self.pentatonic = False
        # loop related variables
        self.midi_ports_last = []
        self.allMidiDevices = []
        self.lastDevCheck = 0

        # self.flushMidi()
        self.allNotes  = [Note(index=i, interface=self) for i in range(128)]
        self.allVoices = [Voice(index=i) for i in range(self.POLYPHONY)]
        self.control   = [0 for i in range(128)]
        self.physicalUnheldNotes = list(np.arange(128))
        self.sustain = False
        self.notesToRelease = []
        self.modWheelReal = 0.25
        self.pitchwheelReal = 1
        self.mostRecentlySpawnedVoice = self.allVoices[0]
        self.mostRecentlyStruckNote = self.allNotes[0]
        self.deviceWhichRecentlyBent = None
        self.roundRobinVoice = 0
        self.pitchwheelRealLp = 1

    def spawnVoice(self):
        # fuck it, round robin
        voice = self.allVoices[self.roundRobinVoice]
        self.mostRecentlySpawnedVoice = voice
        self.roundRobinVoice = (self.roundRobinVoice + 1) % self.POLYPHONY
        
        if self.pentatonic:
            voice.midiIndex = pentatonicFull[msg.note]

        return voice

        # try to pick an unheld note first
        # the one released the longest ago
        if len(self.physicalUnheldNotes):
            retval = sorted(
                self.physicalUnheldNotes, key=lambda x: x.strikeTime, reverse=False
            )[0]
            self.physicalUnheldNotes.remove(retval)
            return retval
        # otherwise, pick the least recently struck
        else:
            retval = sorted(self.allVoices, key=lambda x: x.strikeTime, reverse=False)[
                0
            ]
            return retval

    def checkForNewDevices(self):
        midi_ports = self.midiin.get_ports()
        for i, midi_portname in enumerate(midi_ports):
            if midi_portname not in self.midi_ports_last:
                logger.debug("adding " + midi_portname)
                try:
                    mididev, midi_portno = open_midiinput(midi_portname)
                except (EOFError, KeyboardInterrupt):
                    sys.exit()

                self.allMidiDevices += [(mididev, midi_portname)]
        self.midi_ports_last = midi_ports

    def processMidi(self, devAndMsg):
        dev, msg = devAndMsg
        if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):

            if self.sustain:
                self.notesToRelease += [msg]
                return
            self.physicalUnheldNotes += [msg.note]
            thisNote = self.allNotes[msg.note]
            thisNote.off(msg)

        elif msg.type == "note_on":
            self.mostRecentlyStruckNote = self.allNotes[msg.note]
            self.allNotes[msg.note].on(msg)
            return self.allNotes[msg.note]

        elif msg.type == "pitchwheel":
            # print("PW: " + str(msg.pitch))
            self.pitchwheel = msg.pitch
            self.deviceWhichRecentlyBent = dev
            #print(dev)
            if (
                self.deviceWhichRecentlyBent is not None
                and "INSTRUMENT1" in self.deviceWhichRecentlyBent
            ):
                self.pitchwheel *= 12
            amountchange = self.pitchwheel / 8192.0
            octavecount = 2 / 12
            self.pitchwheelReal = pow(2, amountchange * octavecount)
            # print("PWREAL " + str(self.pitchwheelReal))
            # self.setAllIncrements()
            self.pitchWheel(self.pitchwheelReal)

        elif msg.type == "control_change":

            event = "control[" + str(msg.control) + "]"
            print(event)
            self.control[msg.control] = msg.value
            # print(event)
            # sustain pedal
            if msg.control == 64:
                print(msg.value)
                if msg.value:
                    self.sustain = True
                else:
                    self.sustain = False
                    for note in self.notesToRelease:
                        self.processMidi((dev, note))
                        # self.voiceOff(voice)
                    self.notesToRelease = []

            # mod wheel
            elif msg.control == 1:
                valReal = msg.value / 127.0
                print(valReal)
                self.modWheelReal = valReal
                self.modWheel(self.modWheelReal)

        elif msg.type == "polytouch":
            self.polytouch = msg.value
            self.polytouchReal = msg.value / 127.0

        elif msg.type == "aftertouch":
            self.aftertouch = msg.value
            self.aftertouchReal = msg.value / 127.0

        # if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
        #    # implement rising mono rate
        #    for heldnote in self.allVoices[::-1]:
        #        if heldnote.held and self.polyphony == self.voicesPerCluster :
        #            self.midi2commands(heldnote.msg)
        #            break

    def flushMidi(self):
        self.getNewMidi()

    def eventLoop(self, processor):

        # check for new devices once a second
        if time.time() - self.lastDevCheck > 1:
            self.lastDevCheck = time.time()
            self.checkForNewDevices()

        for devAndMsg in self.getNewMidi():
            self.processMidi(devAndMsg)

        # put an additive lowpass on the pitch bend
        self.pitchwheelRealLp 
        maxBend = 0.025
        if self.pitchwheelRealLp < self.pitchwheelReal:
            self.pitchwheelRealLp += min(maxBend, self.pitchwheelReal -self.pitchwheelRealLp)
        elif self.pitchwheelRealLp > self.pitchwheelReal:
            self.pitchwheelRealLp -= min(maxBend, self.pitchwheelRealLp-self.pitchwheelReal)
        
        
    def getNewMidi(self):
        # c = sys.stdin.read(1)
        # if c == 'd':
        # 	dtfm_inst.dumpState()
        devAndMsgs = []
        for dev, midi_portname in self.allMidiDevices:
            msg = dev.get_message()
            while msg is not None:
                msg = mido.Message.from_bytes(msg[0])
                devAndMsgs += [(midi_portname, msg)]
                msg = dev.get_message()
        return devAndMsgs
