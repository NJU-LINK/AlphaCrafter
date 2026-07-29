<h1 align="center">AlphaCrafter</h1> 

<p align="center">
  <a href="https://arxiv.org/abs/2605.05580">
    <img src="https://img.shields.io/badge/ArXiv-2605.05580-b31b1b?style=for-the-badge">
  </a>

  <a href="#">
    <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge">
  </a>

  <a href="#">
    <img src="https://img.shields.io/badge/Python-3.10-3776AB?style=for-the-badge&logo=python&logoColor=white">
  </a>
</p>

**AlphaCrafter** is a harness-based multi‑agent framework for cross‑sectional quantitative trading. It integrates LLM‑driven factor discovery, regime‑aware factor selection, and adaptive execution into a single autonomous pipeline.

---

## 🚀 Getting Started

### 1. Launch with Docker Compose
The easiest way to run AlphaCrafter is using Docker Compose, which sets up the container with all necessary volume mounts.

```bash
# Start the container in detached mode
docker-compose up -d
```

### 2. Enter the Container

```bash
# Execute an interactive bash shell inside the container
docker exec -it alphacrafter /bin/bash

# Navigate to the source directory
cd ./alphacrafter
```

### 3. Create a Session in Sandbox

AlphaCrafter manages isolated pipeline runs through a sandbox directory. Each new session is created by copying one of the existing templates (`template_a` or `template_us`). Once copied, you can follow the template's examples to import your dataset and complete the necessary configurations.

**Reference Directory Tree**
```bash
├── sandbox/
│   ├── gpt-5.3-backtest-csi300/    # Example custom session
│   │   ├── config/
│   │   ├── logs/
│   │   ├── persistent/
│   │   │   ├── index_data/         # 000300.SH.csv
│   │   │   ├── stock_data/         # 000001.SH.csv, 000002.SH.csv, ...
│   │   │   ├── stock_financial_statements/  # 000001.SH.json, 000002.SH.json, ...
│   │   │   ├── stock_news/         # 000001.SH.json, 000002.SH.json, ...
│   │   │   ├── account.json
│   │   │   └── date.json
│   │   └── workspace/
```

### 4. Running the Pipeline

The main entry point is `main.py`. Navigate to the `alphacrafter` directory and execute:

```bash
# From within /alphacrafter inside the container
python main.py --session_id gpt-5.3-backtest-csi300 --resume (optional)
```

## 📄 Citation
If you find AlphaCrafter useful for your research, please cite our paper:

```bibtex
@misc{yuan2026alphacrafterharnessingmultiagentworkflows,
      title={AlphaCrafter: Harnessing Multi-Agent Workflows for Cross-Sectional Quantitative Trading}, 
      author={Yishuo Yuan and Jiayi Sheng and Sirui Zeng and Jiaqi Wang and Jiaheng Liu},
      year={2026},
      eprint={2605.05580},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2605.05580}, 
}
```