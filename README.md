# Codex Switch

[中文说明](README.zh-CN.md)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey.svg)

Codex Switch is a desktop and script-based tool for backing up, switching, and inspecting multiple Codex account configurations.

## Demo Screenshot

![Codex Switch demo](assets/screenshot.png)

## Overview

- Tauri desktop app for daily account switching.
- Python scripts for backup, restore, and usage inspection.
- Local account storage and cached usage data.
- macOS, Windows, and Linux support.

## Attribution

This repository is a modified derivative of [Skywang16/codex-account-manager](https://github.com/Skywang16/codex-account-manager).

## License Summary

The upstream project uses the MIT License. MIT is permissive: you may use, modify, publish, and redistribute this project, including on your own GitHub repository.

The main requirement is that you keep the license text and copyright notice in distributed copies or substantial portions of the software.

## Quick Start

### Desktop app

```bash
cd codex-tauri-app
npm install
npm run tauri dev
```

Build release package:

```bash
cd codex-tauri-app
npm run tauri build
```

### Python scripts

```bash
python3 backup_current_account.py
python3 switch_account.py
python3 check_usage.py
python3 codex_account_manager.py
```

## Main Features

- Save the current account configuration.
- Switch between saved accounts.
- View cached usage and refresh current usage from the official endpoint.
- Manage accounts through both Tauri UI and Python scripts.

## Project Structure

```text
codex-switch/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── backup_current_account.py
├── check_usage.py
├── codex_account_manager.py
├── codex_account_manager_web.py
├── switch_account.py
├── usage_checker.py
├── assets/
└── codex-tauri-app/
```

## Release Notes For Your GitHub Repo

- Keep the upstream MIT license text in `LICENSE`.
- Keep attribution to the upstream project in this README.
- Publish desktop installers from GitHub Releases instead of committing them into the repo.
