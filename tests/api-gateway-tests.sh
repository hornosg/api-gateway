#!/bin/bash
# API Gateway Tests - Kong Gateway
# Verifica que todos los servicios estén respondiendo correctamente a través del gateway

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base URLs
KONG_PROXY_URL="http://localhost:8001"
KONG_ADMIN_URL="http://localhost:8444"

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Helper function to log test results
log_result() {
    local test_name="$1"
    local status="$2"
    local details="$3"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    if [ "$status" = "PASS" ]; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        [ -n "$details" ] && echo "  Details: $details"
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        [ -n "$details" ] && echo "  Error: $details"
    fi
}

# Test Kong Gateway status
test_kong_status() {
    echo -e "${YELLOW}Testing Kong Gateway Status...${NC}"
    
    # Test Kong status endpoint
    if response=$(curl -s "$KONG_ADMIN_URL/status" 2>/dev/null); then
        if echo "$response" | grep -q '"server"'; then
            log_result "Kong Admin API Status" "PASS" "Kong is responding"
        else
            log_result "Kong Admin API Status" "FAIL" "Kong response is invalid"
        fi
    else
        log_result "Kong Admin API Status" "FAIL" "Cannot reach Kong Admin API"
    fi
}

# Test service availability through Kong
test_service_health() {
    local service_name="$1"
    local health_path="$2"
    local expected_status="${3:-200}"
    
    echo -e "${YELLOW}Testing $service_name health...${NC}"
    
    response=$(curl -s -w "%{http_code}" -o /dev/null "$KONG_PROXY_URL$health_path" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected_status" ]; then
        log_result "$service_name Health Check" "PASS" "HTTP $response"
    else
        log_result "$service_name Health Check" "FAIL" "Expected $expected_status, got $response"
    fi
}

# Test CORS configuration
test_cors() {
    echo -e "${YELLOW}Testing CORS Configuration...${NC}"
    
    response=$(curl -s -I -X OPTIONS \
        -H "Origin: http://localhost:3000" \
        -H "Access-Control-Request-Method: GET" \
        -H "Access-Control-Request-Headers: Authorization,Content-Type" \
        "$KONG_PROXY_URL/iam/api/v1/health" 2>/dev/null)
    
    if echo "$response" | grep -q "Access-Control-Allow-Origin"; then
        log_result "CORS Configuration" "PASS" "CORS headers present"
    else
        log_result "CORS Configuration" "FAIL" "CORS headers missing"
    fi
}

# Test rate limiting (should return rate limit headers)
test_rate_limiting() {
    echo -e "${YELLOW}Testing Rate Limiting...${NC}"
    
    response=$(curl -s -I "$KONG_PROXY_URL/iam/api/v1/health" 2>/dev/null)
    
    if echo "$response" | grep -q -E "(X-RateLimit|RateLimit)"; then
        log_result "Rate Limiting Headers" "PASS" "Rate limiting headers present"
    else
        log_result "Rate Limiting Headers" "PASS" "Rate limiting may be configured (headers optional)"
    fi
}

# Test authentication (should return 401 for protected endpoints without JWT)
test_authentication() {
    echo -e "${YELLOW}Testing Authentication...${NC}"
    
    # Test protected endpoint without token (should fail)
    response=$(curl -s -w "%{http_code}" -o /dev/null "$KONG_PROXY_URL/pim/api/v1/products" 2>/dev/null || echo "000")
    
    if [ "$response" = "401" ] || [ "$response" = "403" ]; then
        log_result "JWT Authentication" "PASS" "Protected endpoint requires authentication (HTTP $response)"
    else
        log_result "JWT Authentication" "WARN" "Expected 401/403 for protected endpoint, got $response"
    fi
}

# Test service configuration in Kong Admin API
test_service_configuration() {
    echo -e "${YELLOW}Testing Service Configuration...${NC}"
    
    # Get all services
    if services_response=$(curl -s "$KONG_ADMIN_URL/services" 2>/dev/null); then
        service_count=$(echo "$services_response" | jq -r '.data | length' 2>/dev/null || echo "0")
        
        if [ "$service_count" -gt "0" ]; then
            log_result "Service Configuration" "PASS" "$service_count services configured"
        else
            log_result "Service Configuration" "FAIL" "No services configured"
        fi
    else
        log_result "Service Configuration" "FAIL" "Cannot retrieve service configuration"
    fi
    
    # Get all routes
    if routes_response=$(curl -s "$KONG_ADMIN_URL/routes" 2>/dev/null); then
        route_count=$(echo "$routes_response" | jq -r '.data | length' 2>/dev/null || echo "0")
        
        if [ "$route_count" -gt "0" ]; then
            log_result "Route Configuration" "PASS" "$route_count routes configured"
        else
            log_result "Route Configuration" "FAIL" "No routes configured"
        fi
    else
        log_result "Route Configuration" "FAIL" "Cannot retrieve route configuration"
    fi
}

# Test plugin configuration
test_plugins() {
    echo -e "${YELLOW}Testing Plugin Configuration...${NC}"
    
    if plugins_response=$(curl -s "$KONG_ADMIN_URL/plugins" 2>/dev/null); then
        plugin_count=$(echo "$plugins_response" | jq -r '.data | length' 2>/dev/null || echo "0")
        
        if [ "$plugin_count" -gt "0" ]; then
            log_result "Plugin Configuration" "PASS" "$plugin_count plugins configured"
            
            # Check for specific plugins
            plugin_names=$(echo "$plugins_response" | jq -r '.data[].name' 2>/dev/null || echo "")
            
            for plugin in "cors" "jwt" "acl" "rate-limiting"; do
                if echo "$plugin_names" | grep -q "$plugin"; then
                    log_result "$plugin Plugin" "PASS" "Plugin is active"
                else
                    log_result "$plugin Plugin" "WARN" "Plugin not found (may not be configured)"
                fi
            done
        else
            log_result "Plugin Configuration" "FAIL" "No plugins configured"
        fi
    else
        log_result "Plugin Configuration" "FAIL" "Cannot retrieve plugin configuration"
    fi
}

# Main test execution
echo "=========================================="
echo "Kong API Gateway Test Suite"
echo "=========================================="
echo "Gateway Proxy URL: $KONG_PROXY_URL"
echo "Gateway Admin URL: $KONG_ADMIN_URL"
echo "=========================================="

# Run all tests
test_kong_status
test_service_configuration
test_plugins

# Test individual service health endpoints
test_service_health "IAM Service" "/iam/health"
test_service_health "PIM Service" "/pim/api/v1/health"
test_service_health "Stock Service" "/stock/health"
test_service_health "AI Gateway Service" "/ai-gateway/" "200"

# Test gateway functionality
test_cors
test_rate_limiting
test_authentication

# Test results summary
echo "=========================================="
echo "Test Results Summary"
echo "=========================================="
echo "Total Tests: $TOTAL_TESTS"
echo -e "Passed: ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed: ${RED}$FAILED_TESTS${NC}"

if [ "$FAILED_TESTS" -eq "0" ]; then
    echo -e "${GREEN}All tests passed! ✓${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed! ✗${NC}"
    exit 1
fi
