from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pendulum
from google.cloud import storage

from academic_observatory_workflows.config import project_path, TestConfig
from academic_observatory_workflows.orcid_telescope import tasks
from academic_observatory_workflows.orcid_telescope.batch import OrcidBatch, BATCH_REGEX
from academic_observatory_workflows.orcid_telescope.release import OrcidRelease, orcid_batch_names
from observatory_platform.dataset_api import DatasetAPI, DatasetRelease
from observatory_platform.config import module_file_path
from observatory_platform.google.gcs import gcs_blob_name_from_path, gcs_blob_uri, gcs_upload_files
from observatory_platform.airflow.workflow import Workflow
from observatory_platform.sandbox.sandbox_environment import SandboxEnvironment
from observatory_platform.sandbox.test_utils import SandboxTestCase, random_id

FIXTURES_FOLDER = project_path("orcid_telescope", "tests", "fixtures")


@dataclass
class OrcidTestRecords:
    # First run
    first_run_folder = os.path.join(FIXTURES_FOLDER, "first_run")
    first_run_records = [
        {
            "orcid": "0000-0001-5000-5000",
            "path": os.path.join(first_run_folder, "0000-0001-5000-5000.xml"),
            "batch": "000",
        },
        {
            "orcid": "0000-0001-5001-3000",
            "path": os.path.join(first_run_folder, "0000-0001-5001-3000.xml"),
            "batch": "001",
        },
        {
            "orcid": "0000-0001-5002-1000",
            "path": os.path.join(first_run_folder, "0000-0001-5002-1000.xml"),
            "batch": "00X",
        },
        {
            "orcid": "0000-0001-5007-2000",
            "path": os.path.join(first_run_folder, "0000-0001-5007-2000.xml"),
            "batch": "000",
        },
    ]
    first_run_main_table = os.path.join(first_run_folder, "main_table.json")

    # Second run
    second_run_folder = os.path.join(FIXTURES_FOLDER, "second_run")
    second_run_records = [
        {
            "orcid": "0000-0001-5000-5000",
            "path": os.path.join(second_run_folder, "0000-0001-5000-5000.xml"),
            "batch": "000",
        },
        # This record has an "error" key - but still valid for parsing:
        {
            "orcid": "0000-0001-5007-2000",
            "path": os.path.join(second_run_folder, "0000-0001-5007-2000.xml"),
            "batch": "000",
        },
    ]
    second_run_main_table = os.path.join(second_run_folder, "main_table.json")
    upsert_table = os.path.join(second_run_folder, "upsert_table.json")
    delete_table = os.path.join(second_run_folder, "delete_table.json")

    # Invalid Key
    invalid_key_orcid = {
        "orcid": "0000-0001-5010-1000",
        "path": os.path.join(FIXTURES_FOLDER, "0000-0001-5010-1000.xml"),
    }
    # ORICD doesn't match path
    mismatched_orcid = {
        "orcid": "0000-0001-5011-1000",
        "path": os.path.join(FIXTURES_FOLDER, "0000-0001-5011-1000.xml"),
    }

    # Table date fields
    timestamp_fields = ["submission_date", "last_modified_date", "created_date"]


class TestFetchRelease(unittest.TestCase):

    dag_id = "test_orcid"
    run_id = "test_orcid_run"
    bq_main_table_name = "test_orcid"
    bq_upsert_table_name = "test_orcid_upsert"
    bq_delete_table_name = "test_orcid_delete"

    def test_fetch_release(self):
        """Tests the fetch_release function. Runs the function once for first run functionality, then again."""
        data_interval_start = pendulum.datetime(2023, 6, 1)
        data_interval_end = pendulum.datetime(2023, 6, 8)
        env = SandboxEnvironment(project_id=TestConfig.gcp_project_id, data_location=TestConfig.gcp_data_location)
        bq_dataset_id = env.add_dataset()
        api_bq_dataset_id = env.add_dataset()
        with env.create():
            with patch("academic_observatory_workflows.orcid_telescope.tasks.is_first_dag_run") as mock_ifdr:
                mock_ifdr.return_value = True
                actual_release = tasks.fetch_release(
                    dag_id=self.dag_id,
                    run_id=self.run_id,
                    dag_run=MagicMock(),
                    data_interval_start=data_interval_start,
                    data_interval_end=data_interval_end,
                    cloud_workspace=env.cloud_workspace,
                    api_bq_dataset_id=api_bq_dataset_id,
                    bq_dataset_id=bq_dataset_id,
                    bq_main_table_name=self.bq_main_table_name,
                    bq_upsert_table_name=self.bq_upsert_table_name,
                    bq_delete_table_name=self.bq_delete_table_name,
                )

            expected_release = {
                "dag_id": "test_orcid",
                "run_id": "test_orcid_run",
                "cloud_workspace": env.cloud_workspace.to_dict(),
                "bq_dataset_id": bq_dataset_id,
                "bq_main_table_name": "test_orcid",
                "bq_upsert_table_name": "test_orcid_upsert",
                "bq_delete_table_name": "test_orcid_delete",
                "start_date": data_interval_start.timestamp(),
                "end_date": data_interval_end.timestamp(),
                "prev_release_end": pendulum.instance(datetime.datetime.min).timestamp(),
                "prev_latest_modified_record": pendulum.instance(datetime.datetime.min).timestamp(),
                "is_first_run": True,
            }
            self.assertEqual(expected_release, actual_release)

            # Populate the API with a release
            api = DatasetAPI(bq_project_id=env.cloud_workspace.project_id, bq_dataset_id=api_bq_dataset_id)
            api.seed_db()
            release = OrcidRelease.from_dict(actual_release)
            dataset_release = DatasetRelease(
                dag_id=self.dag_id,
                entity_id="orcid",
                dag_run_id=self.run_id,
                created=pendulum.now(),
                modified=pendulum.now(),
                changefile_start_date=release.start_date,
                changefile_end_date=release.end_date,
                extra={"latest_modified_record_date": data_interval_end.to_iso8601_string()},
            )
            api.add_dataset_release(dataset_release)

            # Check that fetch_release behaves differently now
            data_interval_start = pendulum.datetime(2023, 6, 8)
            data_interval_end = pendulum.datetime(2023, 6, 15)
            actual_release = tasks.fetch_release(
                dag_id=self.dag_id,
                run_id=self.run_id,
                dag_run=MagicMock(),
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
                cloud_workspace=env.cloud_workspace,
                api_bq_dataset_id=api_bq_dataset_id,
                bq_dataset_id=bq_dataset_id,
                bq_main_table_name=self.bq_main_table_name,
                bq_upsert_table_name=self.bq_upsert_table_name,
                bq_delete_table_name=self.bq_delete_table_name,
            )

            expected_release = {
                "dag_id": "test_orcid",
                "run_id": "test_orcid_run",
                "cloud_workspace": env.cloud_workspace.to_dict(),
                "bq_dataset_id": bq_dataset_id,
                "bq_main_table_name": "test_orcid",
                "bq_upsert_table_name": "test_orcid_upsert",
                "bq_delete_table_name": "test_orcid_delete",
                "start_date": data_interval_start.timestamp(),
                "end_date": data_interval_end.timestamp(),
                "prev_release_end": pendulum.instance(data_interval_start).timestamp(),
                "prev_latest_modified_record": pendulum.instance(data_interval_start).timestamp(),
                "is_first_run": False,
            }
            self.assertEqual(expected_release, actual_release)


class TestCreateOrcidBatchManifest(SandboxTestCase):
    dag_id = "orcid"
    aws_key = (os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY"))
    aws_region_name = os.getenv("AWS_DEFAULT_REGION")

    def test_create_orcid_batch_manifest(self):
        """Tests the create_orcid_batch_manifest function"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            download_dir = os.path.join(tmp_dir, "download")
            transform_dir = os.path.join(tmp_dir, "transform")
            test_batch_str = "12X"
            # Create a batch for testing
            test_batch = OrcidBatch(download_dir, transform_dir, test_batch_str)

            # Upload the .xml files to the test bucket
            client = storage.Client()
            bucket_id = f"orcid_test_{random_id()}"
            bucket = client.create_bucket(bucket_id)

            blob1 = storage.Blob(f"{test_batch_str}/0000-0001-5000-1000.xml", bucket)
            blob1.upload_from_string("Test data 1")
            # Make now the reference time - blob1 should be ignored
            reference_time = pendulum.now()
            blob2 = storage.Blob(f"{test_batch_str}/0000-0001-5000-2000.xml", bucket)
            blob2.upload_from_string("Test data 2")
            blob3 = storage.Blob(f"{test_batch_str}/0000-0001-5000-3000.xml", bucket)
            blob3.upload_from_string("Test data 3")
            # Put a blob in a different folder - should be ignored
            blob4 = storage.Blob(f"somewhere_else/{test_batch_str}/0000-0001-5000-4000.xml", bucket)
            blob4.upload_from_string("Test data 4")

            tasks.create_orcid_batch_manifest(orcid_batch=test_batch, reference_time=reference_time, bucket=bucket_id)
            with open(test_batch.manifest_file, "w", newline="") as csvfile:
                reader = csv.reader(csvfile)
                manifest_rows = [row for row in reader]
            bucket = [row[0] for row in manifest_rows]
            blobs = [row[1] for row in manifest_rows]
            orcid = [row[2] for row in manifest_rows]
            modification_times = [row[3] for row in manifest_rows]
            self.assertEqual(len(manifest_rows), 2)
            self.assertEqual(set(blobs), set([blob2.name, blob3.name]))
            self.assertEqual(set(orcid), set(["0000-0001-5000-2000", "0000-0001-5000-3000"]))
            self.assertEqual(set(modification_times), set([blob2.updated.isoformat(), blob3.updated.isoformat()]))


class TestCreateOrcidBatchManifest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.list_blobs_path = "academic_observatory_workflows.orcid_telescope.tasks.gcs_list_blobs"
        self.test_batch_str = "12X"
        self.bucket_name = "test-bucket"

    def test_create_orcid_batch_manifest(self):
        """Tests that the manifest file is created with the correct header and contains the correct blob names and
        modification dates"""

        updated_dates = [
            datetime.datetime(2022, 12, 31),
            datetime.datetime(2023, 1, 1),
            datetime.datetime(2023, 1, 1, 1),
            datetime.datetime(2023, 1, 2),
        ]
        blobs = []
        for i, updated in enumerate(updated_dates):
            blob = MagicMock()
            blob.name = f"{self.test_batch_str}/blob{i+1}"
            blob.bucket.name = self.bucket_name
            blob.updated = updated
            blobs.append(blob)

        reference_date = pendulum.datetime(2023, 1, 1)
        with tempfile.TemporaryDirectory() as tmp_dir:
            transform_dir = os.path.join(tmp_dir, "transform")
            os.mkdir(transform_dir)
            test_batch = OrcidBatch(tmp_dir, transform_dir, self.test_batch_str)
            with patch(self.list_blobs_path, return_value=blobs):
                tasks.create_orcid_batch_manifest(test_batch, reference_date, self.bucket_name)

            # Assert manifest file is created with correct header and content
            with open(test_batch.manifest_file, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["blob_name"], blobs[-2].name)
            self.assertEqual(rows[0]["updated"], str(blobs[-2].updated))
            self.assertEqual(rows[1]["blob_name"], blobs[-1].name)
            self.assertEqual(rows[1]["updated"], str(blobs[-1].updated))

    def test_no_results(self):
        """Tests that the manifest file is not created if there are no blobs modified after the reference date"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            transform_dir = os.path.join(tmp_dir, "transform")
            os.mkdir(transform_dir)
            test_batch = OrcidBatch(tmp_dir, transform_dir, self.test_batch_str)

            # Mock gcs_list_blobs
            blob = MagicMock()
            blob.name = f"{self.test_batch_str}/blob1"
            blob.bucket.name = self.bucket_name
            blob.updated = datetime.datetime(2022, 6, 1)
            with patch(self.list_blobs_path, return_value=[blob]):
                tasks.create_orcid_batch_manifest(test_batch, pendulum.datetime(2023, 1, 1), self.bucket_name)

            # Assert manifest file is created
            self.assertTrue(os.path.exists(test_batch.manifest_file))
            with open(test_batch.manifest_file, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            self.assertEqual(len(rows), 0)


class TestTransformOrcidRecord(unittest.TestCase):
    def test_valid_record(self):
        """Tests that a valid ORCID record with 'record' section is transformed correctly"""
        for asset in OrcidTestRecords.first_run_records:
            orcid = asset["orcid"]
            path = asset["path"]
            transformed_record = tasks.transform_orcid_record(path)
            self.assertIsInstance(transformed_record, dict)
            self.assertEqual(transformed_record["orcid_identifier"]["path"], orcid)

    def test_error_record(self):
        """Tests that an ORCID record with 'error' section is transformed correctly"""
        error_record = OrcidTestRecords.second_run_records[1]
        orcid = error_record["orcid"]
        path = error_record["path"]
        transformed_record = tasks.transform_orcid_record(path)
        self.assertIsInstance(transformed_record, str)
        self.assertEqual(transformed_record, orcid)

    def test_invalid_key_record(self):
        """Tests that an ORCID record with no 'error' or 'record' section raises a Key Error"""
        invaid_key_record = OrcidTestRecords.invalid_key_orcid
        path = invaid_key_record["path"]
        with self.assertRaises(KeyError):
            tasks.transform_orcid_record(path)

    def test_mismatched_orcid(self):
        """Tests that a ValueError is raised if the ORCID in the file name does not match the ORCID in the record"""
        mismatched_orcid = OrcidTestRecords.mismatched_orcid
        path = mismatched_orcid["path"]
        with self.assertRaisesRegex(ValueError, "does not match ORCID in record"):
            tasks.transform_orcid_record(path)


class TestExtras(unittest.TestCase):
    def test_latest_modified_record_date(self):
        """Tests that the latest_modified_record_date function returns the correct date"""
        # Create a temporary manifest file for the test
        with tempfile.NamedTemporaryFile() as temp_file:
            with open(temp_file.name, "w") as f:
                f.write(",".join(tasks.MANIFEST_HEADER))
                f.write("\n")
                f.write("gs://test-bucket,folder/0000-0000-0000-0001.xml,2023-06-03T00:00:00Z\n")
                f.write("gs://test-bucket,folder/0000-0000-0000-0002.xml,2023-06-03T00:00:00Z\n")
                f.write("gs://test-bucket,folder/0000-0000-0000-0003.xml,2023-06-02T00:00:00Z\n")
                f.write("gs://test-bucket,folder/0000-0000-0000-0004.xml,2023-06-01T00:00:00Z\n")

            # Call the function and assert the result
            expected_date = pendulum.parse("2023-06-03T00:00:00Z")
            actual_date = tasks.latest_modified_record_date(temp_file.name)
            self.assertEqual(actual_date, expected_date)

    def test_orcid_batch_names(self):
        """Tests that the orcid_batch_names function returns the expected results"""
        batch_names = orcid_batch_names()

        # Test that the function returns a list
        self.assertIsInstance(batch_names, list)
        self.assertEqual(len(batch_names), 1100)
        self.assertTrue(all(isinstance(element, str) for element in batch_names))
        self.assertEqual(len(set(batch_names)), len(batch_names))
        # Test that the batch names match the OrcidBatch regex
        for batch_name in batch_names:
            self.assertTrue(re.match(BATCH_REGEX, batch_name))
