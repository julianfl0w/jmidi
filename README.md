# jmidi

The following command opens all available midi devices (dynamically):
```
self.mm = jmidi.MidiManager(
    polyphony=self.POLYPHONY, synthInterface=self.spectralInterface
)
```

spectralInterface must implement
- noteOn()
- noteOff()
- pitchWheel()
- modWheel()

Put this in your main loop:
```
self.mm.eventLoop(self)

```

To inject MIDI (ex for testing):
```
self.mm.processMidi(mido.Message("note_on", note=50, velocity=64, time=6.2))
```

