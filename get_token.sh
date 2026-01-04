#!/bin/bash
curl -X POST http://localhost:5519/login \
  -H "Content-Type: application/json" \
  -d '{"email":"albaraazain88@gmail.com","password":"20102010Qwerty%"}' \
  -s | jq -r '.accessToken'