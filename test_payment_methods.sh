#!/bin/bash
TOKEN=$(curl -X POST http://localhost:5519/login \
  -H "Content-Type: application/json" \
  -d '{"email":"albaraazain88@gmail.com","password":"20102010Qwerty%"}' \
  -s | jq -r '.accessToken')

echo "=== Testing Payment Method Management ==="

echo -e "\n1. Testing /api/payment-methods:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/payment-methods -s -w "\nHTTP Status: %{http_code}\n" | head -50

echo -e "\n2. Testing /api/paymentMethods:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/paymentMethods -s -w "\nHTTP Status: %{http_code}\n" | head -50

echo -e "\n3. Testing /api/business-settings/payment-methods:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/business-settings/payment-methods -s -w "\nHTTP Status: %{http_code}\n" | head -50

echo -e "\n4. Testing /paymentMethods:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/paymentMethods -s -w "\nHTTP Status: %{http_code}\n" | head -50

echo -e "\n5. Testing POST to check if we can add payment methods:"
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Credit Card","isActive":true}' \
  http://localhost:5519/api/payment-methods -s -w "\nHTTP Status: %{http_code}\n" | head -50