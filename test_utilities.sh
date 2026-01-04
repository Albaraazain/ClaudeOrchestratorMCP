#!/bin/bash
TOKEN=$(curl -X POST http://localhost:5519/login \
  -H "Content-Type: application/json" \
  -d '{"email":"albaraazain88@gmail.com","password":"20102010Qwerty%"}' \
  -s | jq -r '.accessToken')

echo "=== Testing Utility Endpoints ==="

echo -e "\n1. Testing /api/reports:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/reports -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n2. Testing /api/business-settings:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/business-settings -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n3. Testing /api/loyaltyPrograms:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/loyaltyPrograms -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n4. Testing /api/promotions:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/promotions -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n5. Testing /api/stocks:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/stocks -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n6. Testing /api/tableAreas:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/tableAreas -s -w "\nHTTP Status: %{http_code}\n" | head -100

echo -e "\n7. Testing /api/payments:"
curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/payments -s -w "\nHTTP Status: %{http_code}\n" | head -100