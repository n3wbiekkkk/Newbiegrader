#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
set -eu
cd /w
pip install -q -r requirements.txt 2>&1 | tail -1
python3 -m unittest tests.test_queue_admission.QueueAdmission.test_poll_refresh_cannot_replace_active_attempt_ownership -v 2>&1