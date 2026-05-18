# Providers

This document describes how to configure your provider for mini-agent.

## Overview

mini-agent currently only supports an Anthropic-compatible endpoint. You can configure provider in two ways:

1. Environment Variables
2. Configuration directory (`~/.mini-agent/.env`)

## Method 1: Environment Variables

Set your API key as an environment variable. This is useful for temporary configurations or CI/CD environments.

### Claude API

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

### For Custom/Third-Party Providers

If you're using a custom base URL (e.g., OpenRouter, Azure, or other providers):

```bash
export ANTHROPIC_BASE_URL="https://api.custom-provider.com/v1"
export ANTHROPIC_API_KEY="your-api-key-here"
```

## Method 2: Configuration Directory

Store provider configuration in `$HOME/.mini-agent/.env`.

```bash
# For Claude API
echo 'ANTHROPIC_API_KEY="your-api-key-here"' > ~/.mini-agent/.env

# For custom providers
echo 'ANTHROPIC_BASE_URL="https://api.custom-provider.com/v1"' > ~/.mini-agent/.env
echo 'ANTHROPIC_API_KEY="your-api-key-here"' >> ~/.mini-agent/.env
```

## Priority Order

The configuration is loaded in this order (later values override earlier ones):

1. System environment variables
2. `~/.mini-agent/.env` file
