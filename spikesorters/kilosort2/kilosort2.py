from pathlib import Path
import os
import sys
import numpy as np
from typing import Union
import shutil
import json

import spikeextractors as se
from ..basesorter import BaseSorter
from ..utils.shellscript import ShellScript
from ..sorter_tools import get_git_commit, recover_recording

PathType = Union[str, Path]


def check_if_installed(kilosort2_path: Union[str, None]):
    if kilosort2_path is None:
        return False
    assert isinstance(kilosort2_path, str)

    if kilosort2_path.startswith('"'):
        kilosort2_path = kilosort2_path[1:-1]
    kilosort2_path = str(Path(kilosort2_path).absolute())

    if (Path(kilosort2_path) / 'master_kilosort.m').is_file() or (Path(kilosort2_path) / 'main_kilosort.m').is_file():
        return True
    else:
        return False


class Kilosort2Sorter(BaseSorter):
    """
    """

    sorter_name: str = 'kilosort2'
    kilosort2_path: Union[str, None] = os.getenv('KILOSORT2_PATH', None)
    requires_locations = False

    _default_params = {
        'detect_threshold': 6,
        'projection_threshold': [10, 4],
        'preclust_threshold': 8,
        'car': True,
        'minFR': 0.1,
        'minfr_goodchannels': 0.1,
        'freq_min': 150,
        'sigmaMask': 30,
        'nPCs': 3,
        'ntbuff': 64,
        'nfilt_factor': 4,
        'NT': None,
        'keep_good_only': False,
        'chunk_mb': 500,
        'n_jobs_bin': 1
    }

    _params_description = {
        'detect_threshold': "Threshold for spike detection",
        'projection_threshold': "Threshold on projections",
        'preclust_threshold': "Threshold crossings for pre-clustering (in PCA projection space)",
        'car': "Enable or disable common reference",
        'minFR': "Minimum spike rate (Hz), if a cluster falls below this for too long it gets removed",
        'minfr_goodchannels': "Minimum firing rate on a 'good' channel",
        'freq_min': "High-pass filter cutoff frequency",
        'sigmaMask': "Spatial constant in um for computing residual variance of spike",
        'nPCs': "Number of PCA dimensions",
        'ntbuff': "Samples of symmetrical buffer for whitening and spike detection",
        'nfilt_factor': "Max number of clusters per good channel (even temporary ones) 4",
        'NT': "Batch size (if None it is automatically computed)",
        'keep_good_only': "If True only 'good' units are returned",
        'chunk_mb': "Chunk size in Mb for saving to binary format (default 500Mb)",
        'n_jobs_bin': "Number of jobs for saving to binary format (Default 1)"
    }

    sorter_description = """Kilosort2 is a GPU-accelerated and efficient template-matching spike sorter. On top of its 
    predecessor Kilosort, it implements a drift-correction strategy.
    For more information see https://github.com/MouseLand/Kilosort2"""

    installation_mesg = """\nTo use Kilosort2 run:\n
        >>> git clone https://github.com/MouseLand/Kilosort2
    and provide the installation path by setting the KILOSORT2_PATH
    environment variables or using Kilosort2Sorter.set_kilosort2_path().\n\n

    More information on Kilosort2 at:
        https://github.com/MouseLand/Kilosort2
    """

    def __init__(self, **kargs):
        BaseSorter.__init__(self, **kargs)

    @classmethod
    def is_installed(cls):
        return check_if_installed(cls.kilosort2_path)

    @staticmethod
    def get_sorter_version():
        commit = get_git_commit(os.getenv('KILOSORT2_PATH', None))
        if commit is None:
            return 'unknown'
        else:
            return 'git-' + commit

    @staticmethod
    def set_kilosort2_path(kilosort2_path: PathType):
        kilosort2_path = str(Path(kilosort2_path).absolute())
        Kilosort2Sorter.kilosort2_path = kilosort2_path
        try:
            print("Setting KILOSORT2_PATH environment variable for subprocess calls to:", kilosort2_path)
            os.environ["KILOSORT2_PATH"] = kilosort2_path
        except Exception as e:
            print("Could not set KILOSORT2_PATH environment variable:", e)

    def _setup_recording(self, recording, output_folder):
        source_dir = Path(Path(__file__).parent)
        p = self.params

        if not self.is_installed():
            raise Exception(Kilosort2Sorter.installation_mesg)

        # prepare electrode positions for this group (only one group, the split is done in basesorter)
        groups = [1] * recording.get_num_channels()
        positions = np.array(recording.get_channel_locations())
        if positions.shape[1] != 2:
            raise RuntimeError("3D 'location' are not supported. Set 2D locations instead")

        # save binary file
        input_file_path = output_folder / 'recording.dat'
        recording.write_to_binary_dat_format(input_file_path, dtype='int16', chunk_mb=p["chunk_mb"],
                                             n_jobs=p["n_jobs_bin"], verbose=self.verbose)

        if p['car']:
            use_car = 1
        else:
            use_car = 0

        # read the template txt files
        with (source_dir / 'kilosort2_master.m').open('r') as f:
            kilosort2_master_txt = f.read()
        with (source_dir / 'kilosort2_config.m').open('r') as f:
            kilosort2_config_txt = f.read()
        with (source_dir / 'kilosort2_channelmap.m').open('r') as f:
            kilosort2_channelmap_txt = f.read()

        # make substitutions in txt files
        kilosort2_master_txt = kilosort2_master_txt.format(
            kilosort2_path=str(
                Path(Kilosort2Sorter.kilosort2_path).absolute()),
            output_folder=str(output_folder),
            channel_path=str(
                (output_folder / 'kilosort2_channelmap.m').absolute()),
            config_path=str((output_folder / 'kilosort2_config.m').absolute()),
        )

        if p['NT'] is None:
            p['NT'] = 64 * 1024 + p['ntbuff']
        else:
            p['NT'] = p['NT'] // 32 * 32  # make sure is multiple of 32

        kilosort2_config_txt = kilosort2_config_txt.format(
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            dat_file=str((output_folder / 'recording.dat').absolute()),
            projection_threshold=p['projection_threshold'],
            preclust_threshold=p['preclust_threshold'],
            minfr_goodchannels=p['minfr_goodchannels'],
            minFR=p['minFR'],
            freq_min=p['freq_min'],
            sigmaMask=p['sigmaMask'],
            kilo_thresh=p['detect_threshold'],
            use_car=use_car,
            nPCs=int(p['nPCs']),
            ntbuff=int(p['ntbuff']),
            nfilt_factor=int(p['nfilt_factor']),
            NT=int(p['NT'])
        )

        kilosort2_channelmap_txt = kilosort2_channelmap_txt.format(
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            xcoords=[p[0] for p in positions],
            ycoords=[p[1] for p in positions],
            kcoords=groups
        )

        for fname, txt in zip(['kilosort2_master.m', 'kilosort2_config.m',
                               'kilosort2_channelmap.m'],
                              [kilosort2_master_txt, kilosort2_config_txt,
                               kilosort2_channelmap_txt]):
            with (output_folder / fname).open('w') as f:
                f.write(txt)

        shutil.copy(str(source_dir.parent / 'utils' / 'writeNPY.m'), str(output_folder))
        shutil.copy(str(source_dir.parent / 'utils' / 'constructNPYheader.m'), str(output_folder))

    def _run(self, recording, output_folder):
        recording = recover_recording(recording)
        if 'win' in sys.platform and sys.platform != 'darwin':
            shell_cmd = '''
                        {disk_move}
                        cd {tmpdir}
                        matlab -nosplash -wait -log -r kilosort2_master
                    '''.format(disk_move=str(output_folder)[:2], tmpdir=output_folder)
        else:
            shell_cmd = '''
                        #!/bin/bash
                        cd "{tmpdir}"
                        matlab -nosplash -nodisplay -log -r kilosort2_master
                    '''.format(tmpdir=output_folder)
        shell_script = ShellScript(shell_cmd, script_path=output_folder / f'run_{self.sorter_name}',
                                   log_path=output_folder / f'{self.sorter_name}.log', verbose=self.verbose)
        shell_script.start()
        retcode = shell_script.wait()

        if retcode != 0:
            raise Exception('kilosort2 returned a non-zero exit code')

    @staticmethod
    def get_result_from_folder(output_folder):
        output_folder = Path(output_folder)
        with (output_folder / 'spikeinterface_params.json').open('r') as f:
            sorter_params = json.load(f)['sorter_params']
        sorting = se.KiloSortSortingExtractor(folder_path=output_folder, keep_good_only=sorter_params['keep_good_only'])
        return sorting
