#!/bin/bash

echo "════════════════════════════════════════════════════════════"
echo "📦 Installing MCP Server for Claude Orchestrator"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check Python version
echo "🔍 Checking Python version..."
python3 --version
if [ $? -ne 0 ]; then
    echo "❌ Python 3 not found. Please install Python 3.10 or higher."
    exit 1
fi

# Create virtual environment (optional but recommended)
echo ""
echo "🏗️ Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo ""
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed successfully"
else
    echo "❌ Failed to install dependencies"
    exit 1
fi

# Test import
echo ""
echo "🧪 Testing MCP server..."
python3 -c "from mcp_server import mcp; print('✅ MCP server imports successfully')"

if [ $? -ne 0 ]; then
    echo "❌ MCP server import failed"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ MCP Server Installation Complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📝 To configure Claude Desktop:"
echo "   1. Copy the contents of claude_desktop_config.json"
echo "   2. Add to your Claude Desktop configuration at:"
echo "      - macOS: ~/Library/Application Support/Claude/config.json"
echo "      - Windows: %APPDATA%/Claude/config.json"
echo "      - Linux: ~/.config/Claude/config.json"
echo ""
echo "🚀 To run the MCP server manually:"
echo "   source venv/bin/activate"
echo "   python -m mcp_server"
echo ""
echo "📖 Available MCP Tools:"
echo "   • create_task - Create new orchestration task"
echo "   • deploy_agent - Deploy headless Claude agent"
echo "   • get_task_status - Check task and agent status"
echo "   • check_spiral_conditions - Check for spiral violations"
echo "   • kill_agent - Terminate an agent"
echo "   • update_agent_progress - Update agent progress"
echo "   • run_pattern - Run orchestration patterns"
echo ""
echo "📚 Available MCP Resources:"
echo "   • task://list - List all tasks"
echo "   • task://{id} - Get specific task details"
echo "   • rules://spawn - View spawn rules"
echo "   • config://limits - View system limits"
echo "   • logs://{task_id}/{agent_id} - Get agent logs"
echo ""