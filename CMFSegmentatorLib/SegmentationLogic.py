import os
import sys
from pathlib import Path

import qt
import slicer

from .Signal import Signal


class SegmentationLogic:
    def __init__(self):
        self.inferenceFinished = Signal()
        self.errorOccurred = Signal("str")

        fileDir = Path(__file__).parent
        mlResourcesDir = fileDir.joinpath("..", "Resources", "ML").resolve()
        assert mlResourcesDir.exists()

        # dir containing the result of the nnunet experiment (weight checkpoints, dataset.json, plans.json, ...)
        self._nnunet_results_folder = mlResourcesDir.joinpath("CMFSegmentationModel")
        assert self._nnunet_results_folder.exists()

        self.inferenceProcess = qt.QProcess()
        self.inferenceProcess.finished.connect(self.onFinished)
        self.inferenceProcess.errorOccurred.connect(self.onErrorOccurred)

        self._tmpDir = qt.QTemporaryDir()

    def onErrorOccurred(self, *_):
        self.errorOccurred(bytes(self.inferenceProcess.readAllStandardError().data()).decode())

    def onFinished(self, *_):
        self.inferenceFinished()

    def startCmfSegmentation(self, volumeNode: "slicer.vtkMRMLScalarVolumeNode") -> None:
        """Run the segmentation on a slicer volumeNode, get the result as a segmentationNode"""
        self._stopInferenceProcess()
        self._prepareInferenceDir(volumeNode)
        self._startInferenceProcess()

    def stopCmfSegmentation(self):
        self._stopInferenceProcess()

    def waitForSegmentationFinished(self):
        self.inferenceProcess.waitForFinished(-1)

    def loadCmfSegmentation(self):
        try:
            return slicer.util.loadSegmentation(self._outFile)
        except StopIteration:
            raise RuntimeError(f"Failed to load the segmentation.\nCheck the inference folder content {self._outDir}")

    def _stopInferenceProcess(self):
        if self.inferenceProcess.state() == self.inferenceProcess.Running:
            self.inferenceProcess.kill()

    def _startInferenceProcess(self, device='cuda', step_size=0.5, disable_tta=True):
        """ Run the nnU-Net V2 inference script

        :param device: 'cuda' or 'cpu'
        :param step_size: step size for the sliding window. (smaller = slower but more accurate).
         Must not be larger than 1.
        :param disable_tta: Set this flag to disable test time data augmentation in the form of mirroring.
         Faster, but less accurate inference.
        """
        # setup environment variables
        # not needed, just needs to be an existing directory
        os.environ['nnUNet_preprocessed'] = self._nnunet_results_folder.as_posix()

        # not needed, just needs to be an existing directory
        os.environ['nnUNet_raw'] = self._nnunet_results_folder.as_posix()
        os.environ['nnUNet_results'] = self._nnunet_results_folder.as_posix()

        dataset_name = 'Dataset111_453CT'
        configuration = '3d_fullres'
        python_scripts_dir = Path(os.path.dirname(sys.executable)).joinpath("..", "lib", "Python", "Scripts")

        # Construct the command for the nnunnet inference script
        args = [
            "-i", self._inDir.as_posix(),
            "-o", self._outDir.as_posix(),
            "-d", dataset_name,
            "-c", configuration,
            "-f", "0",
            "-step_size", step_size,
            "-device", device
        ]

        if disable_tta:
            args.append("--disable_tta")

        program = next(python_scripts_dir.glob("nnUNetv2_predict*")).resolve()
        self.inferenceProcess.start(program, args)

    @property
    def _outFile(self) -> str:
        return next(file for file in self._outDir.rglob("*.nii*")).as_posix()

    def _prepareInferenceDir(self, volumeNode):
        self._tmpDir.remove()
        self._outDir.mkdir(parents=True)
        self._inDir.mkdir(parents=True)

        # Name of the volume should match expected nnUNet conventions
        volumePath = self._inDir.joinpath("volume_0000.nii.gz")
        assert slicer.util.exportNode(volumeNode, volumePath)
        assert volumePath.exists(), "Failed to export volume for segmentation."

    @property
    def _outDir(self):
        return Path(self._tmpDir.path()).joinpath("output")

    @property
    def _inDir(self):
        return Path(self._tmpDir.path()).joinpath("input")