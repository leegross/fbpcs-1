/*
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include <gflags/gflags.h>
#include <string>

#include "folly/init/Init.h"
#include "folly/logging/xlog.h"
#include "folly/Format.h"
#include <fbpcf/mpc/EmpGame.h>

#include "fbpcs/emp_games/attribution/CostEstimation.h"
#include <fbpcf/aws/AwsSdk.h>
#include <fbpcf/mpc/MpcAppExecutor.h>
#include "fbpcs/emp_games/attribution/decoupled_attribution/MainUtil.h"
#include "fbpcs/emp_games/attribution/decoupled_attribution/Constants.h"
#include "fbpcs/emp_games/attribution/decoupled_attribution/AttributionOptions.h"


int main(int argc, char* argv[]) {

  measurement::private_attribution::CostEstimation cost =
            measurement::private_attribution::CostEstimation("computation_experimental");
  cost.start();

  folly::init(&argc, &argv);
  gflags::ParseCommandLineFlags(&argc, &argv, true);
  fbpcf::AwsSdk::aquire();

  XLOGF(INFO, "Party: {}", FLAGS_party);
  XLOGF(INFO, "Server IP: {}", FLAGS_server_ip);
  XLOGF(INFO, "Port: {}", FLAGS_port);
  XLOGF(INFO, "Base input path: {}", FLAGS_input_base_path);
  XLOGF(INFO, "Base output path: {}", FLAGS_output_base_path);

  try {
    auto [inputFilenames, outputFilenames] =
        aggregation::private_attribution::getIOFilenames(
            FLAGS_num_files,
            FLAGS_input_base_path,
            FLAGS_output_base_path,
            FLAGS_file_start_index,
            FLAGS_use_postfix);
    int16_t concurrency = static_cast<int16_t>(FLAGS_concurrency);

    if (FLAGS_party == static_cast<int>(fbpcf::Party::Alice)) {
      XLOGF(INFO, "Attribution Rules: {}", FLAGS_attribution_rules);

      XLOG(INFO)
          << "Starting attribution as Publisher, will wait for Partner...";
      if (FLAGS_use_xor_encryption) {
        aggregation::private_attribution::startAttributionAppsForShardedFiles<
            aggregation::private_attribution::PUBLISHER,
            fbpcf::Visibility::Xor>(
            inputFilenames,
            outputFilenames,
            concurrency,
            FLAGS_server_ip,
            FLAGS_port,
            FLAGS_attribution_rules);
      } else {
        aggregation::private_attribution::startAttributionAppsForShardedFiles<
            aggregation::private_attribution::PUBLISHER,
            fbpcf::Visibility::Public>(
            inputFilenames,
            outputFilenames,
            concurrency,
            FLAGS_server_ip,
            FLAGS_port,
            FLAGS_attribution_rules);
      }

    } else if (FLAGS_party == static_cast<int>(fbpcf::Party::Bob)) {
      XLOG(INFO)
          << "Starting attribution as Partner, will wait for Publisher...";
      if (FLAGS_use_xor_encryption) {
        aggregation::private_attribution::startAttributionAppsForShardedFiles<
            aggregation::private_attribution::PARTNER,
            fbpcf::Visibility::Xor>(
            inputFilenames,
            outputFilenames,
            concurrency,
            FLAGS_server_ip,
            FLAGS_port,
            FLAGS_attribution_rules);
      } else {
        aggregation::private_attribution::startAttributionAppsForShardedFiles<
            aggregation::private_attribution::PARTNER,
            fbpcf::Visibility::Public>(
            inputFilenames,
            outputFilenames,
            concurrency,
            FLAGS_server_ip,
            FLAGS_port,
            FLAGS_attribution_rules);
      }

    } else {
      XLOGF(FATAL, "Invalid Party: {}", FLAGS_party);
    }
  } catch (const std::exception& e) {
    XLOG(ERR) << "Error: Exception caught in Attribution run.\n \t error msg: "
              << e.what() << "\n \t input directory: " << FLAGS_input_base_path;
    std::exit(1);
  }

  cost.end();
  XLOG(INFO, cost.getEstimatedCostString());

  if (FLAGS_run_name != "" && FLAGS_party == static_cast<int>(fbpcf::Party::Alice)) {
    XLOGF(INFO, "{}", cost.writeToS3(
                            FLAGS_run_name,
                            cost.getEstimatedCostDynamic(
                                  FLAGS_run_name,
                                  FLAGS_attribution_rules,
                                  FLAGS_aggregators)));
  }

  return 0;
}
