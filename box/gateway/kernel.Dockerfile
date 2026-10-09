# The reader's kernel machine: torch + CUDA (prebuilt, so a cold build only adds Jupyter), Jupyter Server,
# ipykernel. bash + python3 (conda's) are what box's supervisor needs. T4 is sm_75: torch 2.5 still ships it.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
RUN pip install --no-cache-dir "jupyter_server~=2.17" "ipykernel~=7.1"
