# -*- coding: utf-8 -*-
#------------------------------------------------------------------------------
# Name:         reduceChords.py
# Purpose:      Tools for eliminating passing chords, etc.
#
# Authors:      Michael Scott Cuthbert, Josiah Wolf Oberholtzer
#
# Copyright:    Copyright © 2013 Michael Scott Cuthbert and the music21 Project
# License:      LGPL, see license.txt
#------------------------------------------------------------------------------

'''
Automatically reduce a MeasureStack to a single chord or group of chords.
'''

import collections
import itertools
import unittest
from music21 import chord
from music21 import environment
from music21 import meter
from music21 import note
from music21 import pitch
from music21 import stream
from music21 import tie

environLocal = environment.Environment('reduceChords')


#------------------------------------------------------------------------------


def testMeasureStream1():
    '''
    returns a simple measure stream for testing:


    >>> s = analysis.reduceChords.testMeasureStream1()
    >>> s.show('text')
    {0.0} <music21.meter.TimeSignature 4/4>
    {0.0} <music21.chord.Chord C4 E4 G4 C5>
    {2.0} <music21.chord.Chord C4 E4 F4 B4>
    {3.0} <music21.chord.Chord C4 E4 G4 C5>
    '''
    #from music21 import chord
    measure = stream.Measure()
    timeSignature = meter.TimeSignature('4/4')
    chord1 = chord.Chord('C4 E4 G4 C5')
    chord1.quarterLength = 2.0
    chord2 = chord.Chord('C4 E4 F4 B4')
    chord3 = chord.Chord('C4 E4 G4 C5')
    for element in (timeSignature, chord1, chord2, chord3):
        measure.append(element)
    return measure


#------------------------------------------------------------------------------


class ChordReducer(object):
    r'''
    A chord reducer.
    '''

    ### INITIALIZER ###

    def __init__(self):
        self.weightAlgorithm = self.qlbsmpConsonance
        self.maxChords = 3

    ### SPECIAL METHODS ###

    def __call__(
        self,
        inputScore,
        ):
        from music21.analysis import offsetTree
        assert isinstance(inputScore, stream.Score)
        tree = offsetTree.OffsetTree.fromScore(inputScore)

        self.removeVerticalDissonances(tree)
        self.fillBassGaps(tree)
        self.removeShortTimespans(tree)
        self.fillBassGaps(tree)
        self.fillOuterMeasureGaps(tree)
        self.alignHockets(tree)
        self.fillInnerMeasureGaps(tree)

        # convert offset trees into music21 scores
        partwiseReduction = tree.toPartwiseScore()
        chordifiedReduction = tree.toChordifiedScore()

        # reduce chords in chordified reduction
        chordifiedPart = stream.Part()
        for measure in chordifiedReduction:
            reducedMeasure = self.reduceMeasureToNChords(
                measure,
                numChords=3,
                weightAlgorithm=self.qlbsmpConsonance,
                trimBelow=0.25,
                )
            chordifiedPart.append(reducedMeasure)

        # clean up notation in all reduction parts
        partwiseReduction.append(chordifiedPart)
        for part in partwiseReduction:
            self._applyTies(part)

        return partwiseReduction

    ### PRIVATE METHODS ###

    def _applyTies(self, part):
        for one, two in self._iterateElementsPairwise(part):
            if one.isNote and two.isNote:
                if one.pitch == two.pitch:
                    one.tie = tie.Tie('start')
            elif one.isChord and two.isChord:
                if one.pitches == two.pitches:
                    one.tie = tie.Tie('start')

    @staticmethod
    def _getIntervalClassSet(pitches):
        result = set()
        pitches = [pitch.Pitch(x) for x in pitches]
        for i, x in enumerate(pitches):
            for y in pitches[i + 1:]:
                interval = int(abs(x.ps - y.ps))
                interval %= 12
                if 6 < interval:
                    interval = 12 - interval
                result.add(interval)
        return result

    def _iterateElementsPairwise(self, stream):
        elementBuffer = []
        prototype = (
            chord.Chord,
            note.Note,
            note.Rest,
            )
        for element in stream.flat:
            if not isinstance(element, prototype):
                continue
            elementBuffer.append(element)
            if len(elementBuffer) == 2:
                yield tuple(elementBuffer)
                elementBuffer.pop(0)

    ### PUBLIC METHODS ###

    def alignHockets(self, tree):
        r'''
        Aligns hockets between parts in `tree`.
        '''
        for verticalities in tree.iterateVerticalitiesNwise(n=2):
            verticalityOne, verticalityTwo = verticalities
            pitchSetOne = verticalityOne.pitchSet
            pitchSetTwo = verticalityTwo.pitchSet
            if not verticalityOne.isConsonant or \
                not verticalityTwo.isConsonant:
                continue
            if verticalityOne.measureNumber != verticalityTwo.measureNumber:
                continue
            if verticalityOne.pitchSet == verticalityTwo.pitchSet:
                continue
            if pitchSetOne.issubset(pitchSetTwo):
                for timespan in verticalityTwo.startTimespans:
                    tree.remove(timespan)
                    newTimespan = timespan.new(
                        beatStrength=verticalityOne.beatStrength,
                        startOffset=verticalityOne.startOffset,
                        )
                    tree.insert(newTimespan)
            elif pitchSetTwo.issubset(pitchSetOne):
                for timespan in verticalityOne.startTimespans:
                    if timespan.stopOffset < verticalityTwo.startOffset:
                        tree.remove(timespan)
                        newTimespan = timespan.new(
                            stopOffset=verticalityTwo.startOffset,
                            )
                        tree.insert(newTimespan)

    def collapseArpeggios(self, tree):
        r'''
        Collapses arpeggios in `tree`.
        '''
        for verticalities in tree.iterateVerticalitiesNwise(n=2):
            one, two = verticalities
            onePitches = sorted(one.pitchSet)
            twoPitches = sorted(two.pitchSet)
            if onePitches[0].nameWithOctave != twoPitches[0].nameWithOctave:
                continue
            elif one.measureNumber != two.measureNumber:
                continue
            bothPitches = set()
            bothPitches.update([x.nameWithOctave for x in onePitches])
            bothPitches.update([x.nameWithOctave for x in twoPitches])
            bothPitches = sorted([pitch.Pitch(x) for x in bothPitches])
            #if not offsetTree.Verticality.pitchesAreConsonant(bothPitches):
            #    intervalClasses = self._getIntervalClassSet(bothPitches)
            #    if intervalClasses not in (
            #        frozenset([1, 3, 4]),
            #        frozenset([1, 4, 5]),
            #        frozenset([2, 3, 5]),
            #        frozenset([2, 4, 6]),
            #        ):
            #        continue
            horizontalities = tree.unwrapVerticalities(verticalities)
            for unused_part, timespans in horizontalities.iteritems():
                if len(timespans) < 2:
                    continue
                elif timespans[0].pitches == timespans[1].pitches:
                    continue
                bothPitches = timespans[0].pitches + timespans[1].pitches
                sumChord = chord.Chord(bothPitches)
                tree.remove(timespans)
                merged = timespans[0].new(
                    element=sumChord,
                    stopOffset=timespans[1].stopOffset,
                    )
                tree.insert(merged)

    def computeMeasureChordWeights(
        self,
        measureObject,
        weightAlgorithm=None,
        ):
        '''
        Compute measure chord weights:

        ::

            >>> s = analysis.reduceChords.testMeasureStream1().notes
            >>> cr = analysis.reduceChords.ChordReducer()
            >>> cws = cr.computeMeasureChordWeights(s)
            >>> for pcs in sorted(cws):
            ...     print "%18r  %2.1f" % (pcs, cws[pcs])
                (0, 4, 7)  3.0
            (0, 11, 4, 5)  1.0

        Add beatStrength:

        ::

            >>> cws = cr.computeMeasureChordWeights(s,
            ...     weightAlgorithm=cr.quarterLengthBeatStrength)
            >>> for pcs in sorted(cws):
            ...     print "%18r  %2.1f" % (pcs, cws[pcs])
                (0, 4, 7)  2.2
            (0, 11, 4, 5)  0.5

        Give extra weight to the last element in a measure:

        ::

            >>> cws = cr.computeMeasureChordWeights(s,
            ...     weightAlgorithm=cr.quarterLengthBeatStrengthMeasurePosition)
            >>> for pcs in sorted(cws):
            ...     print "%18r  %2.1f" % (pcs, cws[pcs])
                (0, 4, 7)  3.0
            (0, 11, 4, 5)  0.5

        Make consonance count a lot:

        >>> cws = cr.computeMeasureChordWeights(s,
        ...     weightAlgorithm=cr.qlbsmpConsonance)
        >>> for pcs in sorted(cws):
        ...     print "%18r  %2.1f" % (pcs, cws[pcs])
             (0, 4, 7)  3.0
         (0, 11, 4, 5)  0.1
        '''
        if weightAlgorithm is None:
            weightAlgorithm = self.quarterLengthOnly
        presentPCs = {}
        self.positionInMeasure = 0
        self.numberOfElementsInMeasure = len(measureObject)
        for i, c in enumerate(measureObject):
            self.positionInMeasure = i
            if c.isNote:
                p = tuple(c.pitch.pitchClass)
            else:
                p = tuple(set([x.pitchClass for x in c.pitches]))
            if p not in presentPCs:
                presentPCs[p] = 0.0
            presentPCs[p] += weightAlgorithm(c)
        self.positionInMeasure = 0
        self.numberOfElementsInMeasure = 0
        return presentPCs

    def fillBassGaps(self, tree):
        def procedure(timespan):
            verticality = tree.getVerticalityAt(timespan.startOffset)
            return verticality.bassTimespan
        for part, subtree in tree.toPartwiseOffsetTrees().iteritems():
            timespans = [x for x in subtree]
            for bassTimespan, group in itertools.groupby(timespans, procedure):
                group = list(group)
                if len(group) == 1:
                    timespan = group[0]
                    shouldReplace = False
                    beatStrength = timespan.beatStrength
                    startOffset = timespan.startOffset
                    stopOffset = timespan.stopOffset
                    if bassTimespan.startOffset < group[0].startOffset:
                        shouldReplace = True
                        beatStrength = bassTimespan.beatStrength
                        startOffset = bassTimespan.startOffset
                    if timespan.stopOffset < bassTimespan.stopOffset:
                        shouldReplace = True
                        stopOffset = bassTimespan.stopOffset
                    if shouldReplace:
                        tree.remove(timespan)
                        newTimespan = timespan.new(
                            beatStrength=beatStrength,
                            startOffset=startOffset,
                            stopOffset=stopOffset,
                            )
                        tree.insert(newTimespan)
                    continue
                else:
                    if bassTimespan.startOffset < group[0].startOffset:
                        tree.remove(group[0])
                        newTimespan = group[0].new(
                            beatStrength=bassTimespan.beatStrength,
                            startOffset=bassTimespan.startOffset,
                            )
                        tree.insert(newTimespan)
                        group[0] = newTimespan
                    if group[-1].stopOffset < bassTimespan.stopOffset:
                        tree.remove(group[-1])
                        newTimespan = group[-1].new(
                            stopOffset=bassTimespan.stopOffset,
                            )
                        tree.insert(newTimespan)
                        group[-1] = newTimespan
                for i in range(len(group) - 1):
                    timespanOne, timespanTwo = group[i], group[i + 1]
                    if timespanOne.pitches == timespanTwo.pitches or \
                        timespanOne.stopOffset != timespanTwo.startOffset:
                        newTimespan = timespanOne.new(
                            stopOffset=timespanTwo.stopOffset,
                            )
                        group[i] = newTimespan
                        group[i + 1] = newTimespan
                        tree.remove((timespanOne, timespanTwo))
                        tree.insert(newTimespan)

    def fillInnerMeasureGaps(self, tree):
        r'''
        Fills inner measure gaps in `tree`.
        '''
        for verticality in tree.iterateVerticalities():
            for parentage in verticality.startTimespans:
                nextParentage = tree.findNextParentageInSamePart(parentage)
                if nextParentage is None:
                    nextStartOffset = parentage.measureStopOffset
                else:
                    nextStartOffset = nextParentage.startOffset
                if parentage.stopOffset != nextStartOffset:
                    tree.remove(parentage)
                    parentage = parentage.new(
                        stopOffset=nextStartOffset,
                        )
                    tree.insert(parentage)
                previousParentage = tree.findPreviousParentageInSamePart(
                    parentage)
                if previousParentage is None:
                    continue
                if previousParentage.measureNumber != parentage.measureNumber:
                    continue
                if previousParentage.pitches != parentage.pitches:
                    continue
                tree.remove(parentage)
                tree.remove(previousParentage)
                newParentage = previousParentage.new(
                    stopOffset=parentage.stopOffset,
                    )
                tree.insert(newParentage)

    def fillOuterMeasureGaps(self, tree):
        r'''
        Fills outer measure gaps in `tree`.
        '''
        for verticality in tree.iterateVerticalities():
            for parentage in verticality.startTimespans:
                previousParentage = tree.findPreviousParentageInSamePart(
                    parentage)
                changed = False
                startOffset = parentage.startOffset
                beatStrength = parentage.beatStrength
                if previousParentage is None or \
                    previousParentage.measureNumber != parentage.measureNumber:
                    if parentage.startOffset != parentage.measureStartOffset:
                        changed = True
                        startOffset = parentage.measureStartOffset
                        startVerticality = tree.getVerticalityAt(startOffset)
                        beatStrength = startVerticality.beatStrength
                nextParentage = tree.findNextParentageInSamePart(parentage)
                stopOffset = parentage.stopOffset
                if nextParentage is None or \
                    nextParentage.measureNumber != parentage.measureNumber:
                    if parentage.stopOffset != parentage.measureStopOffset:
                        changed = True
                        stopOffset = parentage.measureStopOffset
                if changed:
                    tree.remove(parentage)
                    newParentage = parentage.new(
                        beatStrength=beatStrength,
                        startOffset=startOffset,
                        stopOffset=stopOffset,
                        )
                    tree.insert(newParentage)

    def qlbsmpConsonance(self, chordObject):
        '''
        Everything from before plus consonance
        '''
        consonanceScore = 1.0 if chordObject.isConsonant() else 0.1
        if self.positionInMeasure == self.numberOfElementsInMeasure - 1:
            # call beatStrength 1
            weight = chordObject.quarterLength
        else:
            weight = self.quarterLengthBeatStrengthMeasurePosition(chordObject)
        weight *= consonanceScore
        return weight

    def quarterLengthBeatStrength(self, chordObject):
        weight = chordObject.quarterLength * chordObject.beatStrength
        return weight

    def quarterLengthBeatStrengthMeasurePosition(self, chordObject):
        if self.positionInMeasure == self.numberOfElementsInMeasure - 1:
            return chordObject.quarterLength  # call beatStrength 1
        else:
            return self.quarterLengthBeatStrength(chordObject)

    def quarterLengthOnly(self, chordObject):
        return chordObject.quarterLength

    def reduceMeasureToNChords(
        self,
        measureObject,
        numChords=1,
        weightAlgorithm=None,
        trimBelow=0.25,
        ):
        '''
        Reduces measure to `n` chords:

        ::

            >>> s = analysis.reduceChords.testMeasureStream1()
            >>> cr = analysis.reduceChords.ChordReducer()

        Reduce to a maximum of 3 chords; though here we will only get one
        because the other chord is below the trimBelow threshold.

        ::

            >>> newS = cr.reduceMeasureToNChords(s, 3,
            ...     weightAlgorithm=cr.qlbsmpConsonance,
            ...     trimBelow=0.3)
            >>> newS.show('text')
            {0.0} <music21.chord.Chord C4 E4 G4 C5>

        ::

            >>> newS[0].quarterLength
            4.0

        '''
        #from music21 import note
        if measureObject.isFlat is False:
            measureObject = measureObject.flat.notes
        else:
            measureObject = measureObject.notes
        chordWeights = self.computeMeasureChordWeights(
            measureObject,
            weightAlgorithm,
            )
        if numChords > len(chordWeights):
            numChords = len(chordWeights)
        sortedChordWeights = sorted(
            chordWeights,
            key=chordWeights.get,
            reverse=True,
            )
        maxNChords = sortedChordWeights[:numChords]
        if len(maxNChords) == 0:
            r = note.Rest()
            r.quarterLength = measureObject.duration.quarterLength
            for c in measureObject:
                measureObject.remove(c)
            measureObject.insert(0, r)
            return measureObject
        maxChordWeight = chordWeights[maxNChords[0]]
        trimmedMaxChords = []
        for pcTuples in maxNChords:
            if chordWeights[pcTuples] >= maxChordWeight * trimBelow:
                trimmedMaxChords.append(pcTuples)
            else:
                break
        currentGreedyChord = None
        currentGreedyChordPCs = None
        currentGreedyChordNewLength = 0.0
        for c in measureObject:
            if c.isNote:
                p = tuple(c.pitch.pitchClass)
            else:
                p = tuple(set([x.pitchClass for x in c.pitches]))
            if p in trimmedMaxChords and p != currentGreedyChordPCs:
                # keep this chord
                if currentGreedyChord is None and c.offset != 0.0:
                    currentGreedyChordNewLength = c.offset
                    c.offset = 0.0
                elif currentGreedyChord is not None:
                    currentGreedyChord.quarterLength = currentGreedyChordNewLength
                    currentGreedyChordNewLength = 0.0
                currentGreedyChord = c
                for n in c:
                    n.tie = None
                    if n.pitch.accidental is not None:
                        n.pitch.accidental.displayStatus = None
                currentGreedyChordPCs = p
                currentGreedyChordNewLength += c.quarterLength
            else:
                currentGreedyChordNewLength += c.quarterLength
                measureObject.remove(c)
        if currentGreedyChord is not None:
            currentGreedyChord.quarterLength = currentGreedyChordNewLength
            currentGreedyChordNewLength = 0.0
        # even chord lengths...
        for i in range(1, len(measureObject)):
            c = measureObject[i]
            cOffsetCurrent = c.offset
            cOffsetSyncop = cOffsetCurrent - int(cOffsetCurrent)
            if round(cOffsetSyncop, 3) in [0.250, 0.125, 0.333, 0.063, 0.062]:
                lastC = measureObject[i - 1]
                lastC.quarterLength -= cOffsetSyncop
                c.offset = int(cOffsetCurrent)
                c.quarterLength += cOffsetSyncop
        return measureObject

    def removeNonChordTones(self, tree):
        r'''
        Removes timespans containing passing and neighbor tones from `tree`.
        '''
        for verticalities in tree.iterateVerticalitiesNwise(n=3):
            if len(verticalities) < 3:
                continue
            horizontalities = tree.unwrapVerticalities(verticalities)
            for unused_part, horizontality in horizontalities.iteritems():
                if not horizontality.hasPassingTone and \
                    not horizontality.hasNeighborTone:
                    continue
                elif horizontality[0].measureNumber != \
                    horizontality[1].measureNumber:
                    continue
                merged = horizontality[0].new(
                    stopOffset=horizontality[1].stopOffset,
                    )
                tree.remove((horizontality[0], horizontality[1]))
                tree.insert(merged)

    def removeShortTimespans(self, tree, duration=0.5):
        r'''
        Removes timespans in `tree` shorter than `duration`.

        Special treatment is given to groups of short timespans if they take up
        an entire measure. In that case, the timespans with the most common
        sets of pitches are kept.
        '''
        def procedure(timespan):
            measureNumber = timespan.measureNumber
            isShort = timespan.duration < duration
            verticality = tree.getVerticalityAt(timespan.startOffset)
            bassTimespan = verticality.bassTimespan
            if bassTimespan is not None:
                if bassTimespan.duration < duration:
                    bassTimespan = None
            return measureNumber, isShort, bassTimespan
        timespansToRemove = []
        for part, subtree in tree.toPartwiseOffsetTrees().iteritems():
            for key, group in itertools.groupby(subtree, procedure):
                measureNumber, isShort, bassTimespan = key
                if not isShort:
                    continue
                group = list(group)
                isEntireMeasure = False
                if group[0].startOffset == group[0].measureStartOffset:
                    if group[-1].stopOffset == group[0].measureStopOffset:
                        isEntireMeasure = True
                if bassTimespan is not None:
                    if group[0].startOffset == bassTimespan.startOffset:
                        if group[-1].stopOffset == bassTimespan.stopOffset:
                            isEntireMeasure = True
                print part, measureNumber, bassTimespan, isEntireMeasure
                for timespan in group:
                    print '\t', timespan
                if isEntireMeasure:
                    counter = collections.Counter()
                    for timespan in group:
                        counter[timespan.pitches] += timespan.duration
                    bestPitches, duration = counter.most_common()[0]
                    print '\t', bestPitches
                    for timespan in group:
                        if timespan.pitches != bestPitches:
                            print '\t\t', timespan
                            timespansToRemove.append(timespan)
                else:
                    timespansToRemove.extend(group)
        tree.remove(timespansToRemove)

    def removeVerticalDissonances(self, tree):
        r'''
        Removes timespans in each dissonant verticality of `tree` whose pitches
        are above the lowest pitch in that verticality.
        '''
        for verticality in tree.iterateVerticalities():
            if verticality.isConsonant:
                continue
            pitchSet = verticality.pitchSet
            lowestPitch = min(pitchSet)
            for timespan in verticality.startTimespans:
                if min(timespan.pitches) != lowestPitch:
                    tree.remove(timespan)


#------------------------------------------------------------------------------


class Test(unittest.TestCase):

    def runTest(self):
        pass

    def testSimpleMeasure(self):
        #from music21 import chord
        s = stream.Measure()
        c1 = chord.Chord('C4 E4 G4 C5')
        c1.quarterLength = 2.0
        c2 = chord.Chord('C4 E4 F4 B4')
        c3 = chord.Chord('C4 E4 G4 C5')
        for c in [c1, c2, c3]:
            s.append(c)


class TestExternal(unittest.TestCase):

    def runTest(self):
        pass

    def testTrecentoMadrigal(self):
        from music21 import corpus

        score = corpus.parse('PMFC_06_Giovanni-05_Donna').measures(1, 30)
        #score = corpus.parse('bach/bwv846').measures(1, 19)
        #score = corpus.parse('beethoven/opus18no1', 2).measures(1, 3)
        #score = corpus.parse('beethoven/opus18no1', 2).measures(1, 8)
        #score = corpus.parse('PMFC_06_Giovanni-05_Donna').measures(90, 118)
        #score = corpus.parse('PMFC_06_Piero_1').measures(1, 10)
        #score = corpus.parse('PMFC_06-Jacopo').measures(1, 30)
        #score = corpus.parse('PMFC_12_13').measures(1, 40)

        chordReducer = ChordReducer()
        reduction = chordReducer(score)

        for part in reduction:
            score.insert(0, part)

        score.show()


#------------------------------------------------------------------------------
# define presented order in documentation

_DOC_ORDER = []

if __name__ == "__main__":
    #TestExternal().testTrecentoMadrigal()
    import music21
    music21.mainTest(TestExternal)
