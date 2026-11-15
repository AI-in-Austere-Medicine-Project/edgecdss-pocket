"""Two decoders on one utterance (phase 2).

`base` hears the bank's own words, the letters and "[unk]". `spelled` hears those plus
the phonetic spellings of names the model's word list lacks (grammar/sounds_like.json).
Both are fed as the audio arrives. At release the spelled result is used when its text
parses with no unknown word. Otherwise the base result is used if its text parses with no
unknown word and holds no control word: a control word ("confirm", "cancel") is only ever
taken from the spelled decoder, never from the fallback. Otherwise the spelled text goes to
the parser, which refuses it.
"""
import json

from grammar.parser import parse
from voice import spoken

RATE = 16000


class Hearing:
    def __init__(self, model, grammar: dict, vocab):
        import vosk
        vosk.SetLogLevel(-1)
        self.vosk, self.model, self.vocab = vosk, model, vocab
        self.base = json.dumps(grammar["base_words"])
        self.full = json.dumps(grammar["words"])

    def start(self):
        return Utterance(self.vosk.KaldiRecognizer(self.model, RATE, self.base),
                         self.vosk.KaldiRecognizer(self.model, RATE, self.full), self.vocab)


class Utterance:
    def __init__(self, base, spelled, vocab):
        self.recs, self.vocab = (base, spelled), vocab

    def feed(self, data: bytes):
        for r in self.recs:
            r.AcceptWaveform(data)

    def finish(self) -> tuple:
        """(what was heard, the text for the parser, "spelled" | "base")."""
        heard = json.loads(self.recs[1].FinalResult())["text"]
        text = spoken.normalise(heard)
        if heard and not parse(text, self.vocab).unknown:
            return heard, text, "spelled"
        base = json.loads(self.recs[0].FinalResult())["text"]
        btext = spoken.normalise(base, {})
        p = parse(btext, self.vocab)
        if base and not p.unknown and not p.controls:
            return base, btext, "base"
        return heard, text, "spelled"
