import argparse
import os
import sys
import json
import time
import shutil

# Asegurar importacion de acestep 1.5
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "ace_step_1.5_repo"))
sys.path.insert(0, project_root)

# Parche temporal para que las librerias no crasheen si buscan dependencias viejas
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

try:
    from loguru import logger
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams, GenerationConfig, generate_music
except ImportError as e:
    print(f"Error importando ACE-Step 1.5: {e}")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--lyrics", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output_path", required=True)
    parser.add_argument("--device_id", default="0")
    parser.add_argument("--seed", type=int, default=-1)
    args = parser.parse_args()

    models_dir = os.path.join(os.path.dirname(__file__), "models")

    logger.info("Initializing LLM handler (1.7B — mejor articulacion en español)...")
    llm_handler = LLMHandler()
    status_msg, success = llm_handler.initialize(
        checkpoint_dir=models_dir,
        lm_model_path="acestep-5Hz-lm-1.7B",
        backend="pt",  # 'pt' fallback if vllm/mlx not available
        device=f"cuda:{args.device_id}",
        offload_to_cpu=True,
        dtype=None
    )
    if not success:
        logger.error(f"LLM init failed: {status_msg}")
        sys.exit(1)

    logger.info("Initializing DiT handler (turbo)...")
    dit_handler = AceStepHandler()
    
    # Checkpoints junction trick
    checkpoints_symlink = os.path.join(project_root, "checkpoints")
    if not os.path.exists(checkpoints_symlink):
        try:
            import _winapi
            _winapi.CreateJunction(models_dir, checkpoints_symlink)
        except Exception as e:
            logger.warning(f"Failed to create junction: {e}")
            pass

    # El modelo DiT turbo esta dentro de ace-step-1.5/acestep-v15-turbo
    status_msg, success = dit_handler.initialize_service(
        project_root=project_root,
        config_path="ace-step-1.5/acestep-v15-turbo",
        device=f"cuda:{args.device_id}",
        offload_to_cpu=True,
        offload_dit_to_cpu=True,
    )
    if not success:
        logger.error(f"DiT init failed: {status_msg}")
        sys.exit(1)

    params = GenerationParams(
        task_type="text2music",
        thinking=True,
        caption=args.prompt,
        lyrics=args.lyrics,
        vocal_language="es",       # Español nativo — activa el modelo fonético correcto
        duration=args.duration,
        inference_steps=8,         # Turbo: óptimo para RTX 4060
        seed=args.seed,
        # Parámetros de calidad 2026 (investigación industria):
        lm_negative_prompt=(
            "off pitch, out of tune, flat notes, spoken word, talking, speech, "
            "low energy, lifeless, emotionless, monotonous, silence, empty, "
            "instrumental only, bad vocal mixing, harsh, distortion, piercing"
        ),
        fade_out_duration=2.5,     # Fade suave al final — evita cortes bruscos
    )

    config = GenerationConfig(
        batch_size=1,
        audio_format="wav"
    )

    save_dir = os.path.dirname(args.output_path)
    os.makedirs(save_dir, exist_ok=True)

    result = generate_music(
        dit_handler,
        llm_handler,
        params=params,
        config=config,
        save_dir=save_dir
    )

    if result.success and len(result.audios) > 0:
        generated_file = result.audios[0].get("path")
        if generated_file and os.path.exists(generated_file):
            shutil.move(generated_file, args.output_path)
            logger.info(f"Success! Saved to {args.output_path}")
        else:
            logger.error("Generated file missing.")
            sys.exit(1)
    else:
        logger.error(f"Generation failed: {result.status_message}")
        sys.exit(1)

if __name__ == "__main__":
    main()
