#!/bin/bash
TOKEN=$(curl -X POST http://localhost:5519/login \
  -H "Content-Type: application/json" \
  -d '{"email":"albaraazain88@gmail.com","password":"20102010Qwerty%"}' \
  -s | jq -r '.accessToken')

echo "=== Testing Branch Context in Dashboard ==="

# Get properties first
echo -e "\n1. Getting properties list:"
PROPERTIES=$(curl -H "Authorization: Bearer $TOKEN" http://localhost:5519/api/properties -s)
echo "$PROPERTIES" | jq '.'

# Extract first property ID if exists
PROPERTY_ID=$(echo "$PROPERTIES" | jq -r '.items[0].id // empty')

if [ -n "$PROPERTY_ID" ]; then
  echo -e "\n2. Testing dashboard with property header:"
  curl -H "Authorization: Bearer $TOKEN" \
       -H "X-Property-Id: $PROPERTY_ID" \
       http://localhost:5519/dashboard -s | jq '.summary'

  echo -e "\n3. Testing dashboard with property query param:"
  curl -H "Authorization: Bearer $TOKEN" \
       "http://localhost:5519/dashboard?propertyId=$PROPERTY_ID" -s | jq '.summary'
fi

echo -e "\n4. Testing reports with branch context:"
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Property-Id: $PROPERTY_ID" \
     http://localhost:5519/api/reports -s | jq '.'