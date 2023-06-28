import logging
import os
import sys
import time
from pathlib import Path

import torch

file_path = os.path.abspath(Path(__file__))
root_dir = str(Path(file_path).parent.parent.parent.absolute())
sys.path.append(root_dir)

from rl_algo_impls.microrts.map_size_policy_picker import (
    MapSizePolicyPicker,
    PickerArgs,
)
from rl_algo_impls.microrts.vec_env.microrts_socket_env import TIME_BUDGET_MS
from rl_algo_impls.runner.config import Config, EnvHyperparams, RunArgs
from rl_algo_impls.runner.running_utils import get_device, load_hyperparams
from rl_algo_impls.shared.vec_env.make_env import make_eval_env
from rl_algo_impls.utils.timing import measure_time

AGENT_ARGS_BY_MAP_SIZE = {
    16: PickerArgs(
        algo="ppo",
        env="Microrts-A6000-finetuned-coac-mayari",
        seed=1,
        best=True,
        use_paper_obs=True,
    ),
    32: PickerArgs(
        algo="ppo",
        env="Microrts-squnet-map32-128ch-selfplay",
        seed=1,
        best=True,
        use_paper_obs=False,
    ),
    64: PickerArgs(
        algo="ppo",
        env="Microrts-squnet-map64-64ch-selfplay",
        seed=1,
        best=True,
        use_paper_obs=False,
    ),
}


def main():
    sys.stderr = open("microrts_python_error.log", "w")
    logging.basicConfig(
        filename="microrts_python.log",
        filemode="w",
        format="%(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logging.info("Log file start")

    MAX_TORCH_THREADS = 16
    if torch.get_num_threads() > MAX_TORCH_THREADS:
        logging.info(
            f"Reducing torch num_threads from {torch.get_num_threads()} to {MAX_TORCH_THREADS}"
        )
        torch.set_num_threads(MAX_TORCH_THREADS)

    run_args = RunArgs(algo="ppo", env="Microrts-agent", seed=1)
    hyperparams = load_hyperparams(run_args.algo, run_args.env)
    env_config = Config(run_args, hyperparams, root_dir)

    env = make_eval_env(env_config, EnvHyperparams(**env_config.env_hyperparams))
    envs_per_size = {
        sz: make_eval_env(
            env_config,
            EnvHyperparams(**env_config.env_hyperparams),
            override_hparams={
                "valid_sizes": [sz],
                "paper_planes_sizes": [sz] if p_args.use_paper_obs else [],
                "fixed_size": True,
            },
        )
        for sz, p_args in AGENT_ARGS_BY_MAP_SIZE.items()
    }
    device = get_device(env_config, env)
    policy = MapSizePolicyPicker(
        AGENT_ARGS_BY_MAP_SIZE, env, device, envs_per_size
    ).eval()

    get_action_mask = getattr(env, "get_action_mask")

    obs = env.reset()
    action_mask = get_action_mask()
    # Runs forever. Java process expected to terminate on own.
    while True:
        act_start = time.perf_counter()
        with measure_time("policy.act"):
            act = policy.act(obs, deterministic=False, action_masks=action_mask)

        act_duration = (time.perf_counter() - act_start) * 1000
        if act_duration >= TIME_BUDGET_MS:
            logging.warn(f"act took too long: {int(act_duration)}ms")
        obs, _, _, _ = env.step(act)

        action_mask = get_action_mask()


if __name__ == "__main__":
    main()
