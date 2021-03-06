import unittest

import pytest
import spikeextractors as se
from spikesorters import YassSorter, run_yass
from spikesorters.tests.common_tests import SorterCommonTestSuite


# This run several tests
@pytest.mark.skipif(not YassSorter.is_installed(), reason='yass not installed')
class YassCommonTestSuite(SorterCommonTestSuite, unittest.TestCase):
    SorterClass = YassSorter


@pytest.mark.skipif(not YassSorter.is_installed(), reason='yass not installed')
def test_run_yass():
    recording, sorting_gt = se.example_datasets.toy_example(num_channels=4, duration=30, seed=0)

    params = YassSorter.default_params()
    sorting = run_yass(recording, **params)

    print(sorting)
    print(sorting.get_unit_ids())
    for unit_id in sorting.get_unit_ids():
        print('unit #', unit_id, 'nb', len(sorting.get_unit_spike_train(unit_id)))


if __name__ == '__main__':
    test_run_yass()
    YassCommonTestSuite().test_with_BinDatRecordingExtractor()
