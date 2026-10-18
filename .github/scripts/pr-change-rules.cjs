const SOURCE = 'Source code';
const CATEGORIES = [
  {
    name: SOURCE,
    icon: '🟣',
    matches: path => path.startsWith('src/mini_agent/'),
  },
  {
    name: 'Tests & fixtures',
    icon: '🟢',
    matches: path => path.startsWith('tests/'),
  },
  {
    name: 'Dependencies & lockfiles',
    icon: '📦',
    matches: path => /^(?:pyproject\.toml|uv\.lock)$/.test(path),
  },
  {
    name: 'Developer tools & skills',
    icon: '🛠️',
    matches: path => /^(?:scripts|\.agents|\.devcontainer)\//.test(path),
  },
  {
    name: 'Build, CI & deployment',
    icon: '⚙️',
    matches: path => /^\.github\//.test(path)
      || /^(?:Makefile|uv\.toml|\.python-version|\.pre-commit-config\.yaml|\.gitignore)$/.test(path),
  },
  {
    name: 'Documentation',
    icon: '🔵',
    matches: path => /\.md$/i.test(path) || /^(?:LICENSE|NOTICE)(?:\.[^/]+)?$/.test(path),
  },
  {
    name: 'Unclassified',
    icon: '❔',
    matches: () => true,
  },
];

function classify(path) {
  return CATEGORIES.find(category => category.matches(path)).name;
}

function component(path) {
  const source = path.match(/^src\/mini_agent\/([^/]+)(?:\/([^/]+))?/);
  if (source) {
    const top = source[1];
    if (top.endsWith('.py')) return 'core';
    const second = source[2];
    if (!second || second.endsWith('.py')) return top;
    return `${top}/${second}`;
  }
  if (path.startsWith('tests/')) return 'tests';
  if (path.startsWith('docs/')) return 'docs';
  if (path.startsWith('.github/')) return 'github';
  if (path.startsWith('.agents/skills/')) {
    const name = path.split('/')[2];
    return name ? `skills/${name}` : 'skills';
  }
  if (path.startsWith('.agents/')) return 'agents';
  if (path.startsWith('.devcontainer/')) return 'devcontainer';
  if (path.startsWith('scripts/')) return 'installers';
  return 'repository';
}

module.exports = {SOURCE, CATEGORIES, classify, component};
