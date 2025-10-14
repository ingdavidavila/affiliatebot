const path = require('path');

module.exports = function override(config, env) {
  config.resolve.fallback = {
    ...config.resolve.fallback,
    fs: false, // Disable fs since dotenv can work without it in this context
    path: require.resolve('path-browserify'),
    os: require.resolve('os-browserify/browser'),
  };
  return config;
};