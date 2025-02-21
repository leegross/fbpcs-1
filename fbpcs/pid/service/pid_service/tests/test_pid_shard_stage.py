#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import unittest
from unittest.mock import patch

from fbpcp.entity.container_instance import ContainerInstanceStatus, ContainerInstance
from fbpcs.data_processing.sharding.sharding import ShardType
from fbpcs.data_processing.sharding.sharding_cpp import CppShardingService
from fbpcs.onedocker_binary_config import OneDockerBinaryConfig
from fbpcs.pcf.tests.async_utils import to_sync
from fbpcs.pid.entity.pid_instance import PIDStageStatus
from fbpcs.pid.entity.pid_stages import UnionPIDStage
from fbpcs.pid.service.pid_service.pid_shard_stage import PIDShardStage
from fbpcs.pid.service.pid_service.pid_stage import PIDStage
from fbpcs.pid.service.pid_service.pid_stage_input import PIDStageInput
from libfb.py.asyncio.unittest import AsyncMock
from libfb.py.testutil import data_provider


CONFIG = {"s3_coordination_file": "ip_config"}


class TestPIDShardStage(unittest.TestCase):
    @to_sync
    @patch("fbpcs.pid.repository.pid_instance.PIDInstanceRepository")
    async def test_ready(self, mock_instance_repo):
        stage = PIDShardStage(
            stage=UnionPIDStage.PUBLISHER_SHARD,
            config=CONFIG,
            instance_repository=mock_instance_repo,
            storage_svc="STORAGE",
            onedocker_svc="ONEDOCKER",
            onedocker_binary_config="OD_CONFIG",
        )
        stage_input = PIDStageInput(
            input_paths=["in"],
            output_paths=["out"],
            num_shards=123,
            instance_id="444",
        )

        with patch.object(PIDShardStage, "files_exist") as mock_fe:
            mock_fe.return_value = True
            res = await stage._ready(stage_input)
            self.assertTrue(res)

    @data_provider(
        lambda: ({"wait_for_containers": True}, {"wait_for_containers": False})
    )
    @patch("fbpcs.data_processing.sharding.sharding_cpp.wait_for_containers_async")
    @patch("fbpcp.service.storage.StorageService")
    @patch("fbpcp.service.onedocker.OneDockerService")
    @patch("fbpcs.pid.repository.pid_instance.PIDInstanceRepository")
    @to_sync
    async def test_run(
        self,
        mock_instance_repo,
        mock_onedocker_svc,
        mock_storage_svc,
        mock_wait_for_containers_async,
        wait_for_containers: bool,
    ):
        ip = "192.0.2.0"
        container = ContainerInstance(instance_id="123", ip_address=ip)
        mock_onedocker_svc.start_containers_async = AsyncMock(return_value=[container])
        container.status = (
            ContainerInstanceStatus.COMPLETED
            if wait_for_containers
            else ContainerInstanceStatus.STARTED
        )
        mock_wait_for_containers_async.return_value = [container]
        test_onedocker_binary_config = OneDockerBinaryConfig(
            tmp_directory="/test_tmp_directory/",
            binary_version="latest",
        )
        stage = PIDShardStage(
            stage=UnionPIDStage.PUBLISHER_SHARD,
            config=CONFIG,
            instance_repository=mock_instance_repo,
            storage_svc=mock_storage_svc,
            onedocker_svc=mock_onedocker_svc,
            onedocker_binary_config=test_onedocker_binary_config,
        )
        instance_id = "444"
        stage_input = PIDStageInput(
            input_paths=["in"],
            output_paths=["out"],
            num_shards=123,
            instance_id=instance_id,
        )

        # Basic test: All good
        with patch.object(PIDShardStage, "files_exist") as mock_fe:
            mock_fe.return_value = True
            stage = PIDShardStage(
                stage=UnionPIDStage.PUBLISHER_SHARD,
                config=CONFIG,
                instance_repository=mock_instance_repo,
                storage_svc=mock_storage_svc,
                onedocker_svc=mock_onedocker_svc,
                onedocker_binary_config=test_onedocker_binary_config,
            )
            status = await stage.run(
                stage_input, wait_for_containers=wait_for_containers
            )
            self.assertEqual(
                PIDStageStatus.COMPLETED
                if wait_for_containers
                else PIDStageStatus.STARTED,
                status,
            )

            mock_onedocker_svc.start_containers_async.assert_called_once()
            if wait_for_containers:
                mock_wait_for_containers_async.assert_called_once()
            else:
                mock_wait_for_containers_async.assert_not_called()
            # instance status is updated to READY, STARTED, then COMPLETED
            mock_instance_repo.read.assert_called_with(instance_id)
            self.assertEqual(mock_instance_repo.read.call_count, 4)
            self.assertEqual(mock_instance_repo.update.call_count, 4)

        # Input not ready
        with patch.object(PIDShardStage, "files_exist") as mock_fe:
            mock_fe.return_value = False
            status = await stage.run(
                stage_input, wait_for_containers=wait_for_containers
            )
            self.assertEqual(PIDStageStatus.FAILED, status)

        # Multiple input paths (invariant exception)
        with patch.object(PIDShardStage, "files_exist") as mock_fe:
            with self.assertRaises(ValueError):
                mock_fe.return_value = True
                stage_input.input_paths = ["in1", "in2"]
                stage = PIDShardStage(
                    stage=UnionPIDStage.PUBLISHER_SHARD,
                    config=CONFIG,
                    instance_repository=mock_instance_repo,
                    storage_svc=mock_storage_svc,
                    onedocker_svc=mock_onedocker_svc,
                    onedocker_binary_config=test_onedocker_binary_config,
                )
                status = await stage.run(
                    stage_input, wait_for_containers=wait_for_containers
                )
                self.assertEqual(
                    PIDStageStatus.COMPLETED
                    if wait_for_containers
                    else PIDStageStatus.STARTED,
                    status,
                )

    @data_provider(
        lambda: ({"wait_for_containers": True}, {"wait_for_containers": False})
    )
    @patch.object(CppShardingService, "shard_on_container_async")
    @patch("fbpcp.service.storage.StorageService")
    @patch("fbpcp.service.onedocker.OneDockerService")
    @patch("fbpcs.pid.repository.pid_instance.PIDInstanceRepository")
    @to_sync
    async def test_shard(
        self,
        mock_instance_repo,
        mock_onedocker_svc,
        mock_storage_svc,
        mock_sharder,
        wait_for_containers: bool,
    ):
        with patch.object(PIDStage, "update_instance_containers"):
            test_onedocker_binary_config = OneDockerBinaryConfig(
                tmp_directory="/test_tmp_directory/",
                binary_version="latest",
            )
            stage = PIDShardStage(
                stage=UnionPIDStage.PUBLISHER_SHARD,
                config=CONFIG,
                instance_repository=mock_instance_repo,
                storage_svc=mock_storage_svc,
                onedocker_svc=mock_onedocker_svc,
                onedocker_binary_config=test_onedocker_binary_config,
            )

            test_input_path = "foo"
            test_output_path = "bar"
            test_num_shards = 1
            test_hmac_key = "CoXbp7BOEvAN9L1CB2DAORHHr3hB7wE7tpxMYm07tc0="

            shard_path = PIDShardStage.get_sharded_filepath(test_output_path, 0)
            self.assertEqual(f"{test_output_path}_0", shard_path)

            res = await stage.shard(
                "123",
                test_input_path,
                test_output_path,
                test_num_shards,
                test_hmac_key,
                wait_for_containers=wait_for_containers,
            )
            self.assertEqual(
                PIDStageStatus.COMPLETED
                if wait_for_containers
                else PIDStageStatus.STARTED,
                res,
            )

            mock_sharder.assert_called_once_with(
                ShardType.HASHED_FOR_PID,
                test_input_path,
                output_base_path=test_output_path,
                file_start_index=0,
                num_output_files=test_num_shards,
                onedocker_svc=stage.onedocker_svc,
                binary_version=test_onedocker_binary_config.binary_version,
                tmp_directory=test_onedocker_binary_config.tmp_directory,
                hmac_key=test_hmac_key,
                wait_for_containers=wait_for_containers,
            )
