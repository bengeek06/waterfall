# Contributing to Waterfall 🚀

First off, thank you for considering contributing to Waterfall! It's people like you that make Waterfall such a great tool.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Workflow](#development-workflow)
- [Branch Strategy](#branch-strategy)
- [Coding Conventions](#coding-conventions)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)
- [Testing Requirements](#testing-requirements)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [benjamin@waterfall-project.pro](mailto:benjamin@waterfall-project.pro).

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the issue list as you might find out that you don't need to create one. When you are creating a bug report, please include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples to demonstrate the steps**
- **Describe the behavior you observed and what behavior you expected**
- **Include screenshots if relevant**
- **Include your environment details** (OS, Python version, Node.js version, etc.)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, please include:

- **Use a clear and descriptive title**
- **Provide a detailed description of the suggested enhancement**
- **Explain why this enhancement would be useful**
- **List some examples of how this enhancement would be used**

### Your First Code Contribution

Unsure where to begin? You can start by looking through `good-first-issue` and `help-wanted` issues.

## Development Workflow

We follow a **Git Flow** simplified strategy with three long-lived branches:

```
main (production) → staging (pre-production) → develop (development)
```

### Branch Strategy

#### Long-lived Branches

- **`main`**: Production-ready code
  - Protected branch
  - Only receives merges from `staging`
  - Tagged with version numbers (v1.0.0, v1.1.0, etc.)
  - Triggers production deployment

- **`staging`**: Pre-production/integration environment
  - Integration testing environment
  - Receives merges from `develop` or `release/*` branches
  - Bug fixes via `fix/*` branches
  - Triggers staging deployment

- **`develop`**: Active development
  - Latest development changes
  - Receives merges from `feature/*` branches
  - Base branch for new features

#### Short-lived Branches

All feature and fix branches should be:
- Short-lived (delete after merge)
- Focused on a single feature/fix
- Named according to conventions

### Creating a Feature

```bash
# Start from develop
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/PROJ-123-add-oauth-integration

# Work on your feature
# ... make changes, commit frequently ...

# Keep your branch up to date
git fetch origin
git rebase origin/develop

# Push your feature branch
git push origin feature/PROJ-123-add-oauth-integration

# Create Pull Request to develop
```

### Fixing a Bug in Staging

```bash
# Start from staging
git checkout staging
git pull origin staging

# Create fix branch
git checkout -b fix/PROJ-456-resolve-login-timeout

# Fix the bug
# ... make changes, commit ...

# Push and create PR to staging
git push origin fix/PROJ-456-resolve-login-timeout

# After merge to staging, cherry-pick to develop
git checkout develop
git cherry-pick <commit-hash>
```

### Creating a Release

```bash
# Create release branch from develop
git checkout develop
git pull origin develop
git checkout -b release/v1.2.0

# Bump version numbers, update CHANGELOG
# ... version bumps in package.json, __init__.py, etc. ...

# Commit changes
git commit -m "chore(release): prepare version 1.2.0"

# Push and create PR to staging
git push origin release/v1.2.0

# After testing in staging, merge to main
git checkout main
git merge staging --no-ff
git tag -a v1.2.0 -m "Release version 1.2.0"
git push origin main --tags

# Merge back to develop
git checkout develop
git merge release/v1.2.0
git push origin develop

# Delete release branch
git branch -d release/v1.2.0
git push origin --delete release/v1.2.0
```

### Hotfix for Production

```bash
# Create hotfix from main
git checkout main
git pull origin main
git checkout -b hotfix/critical-security-patch

# Fix the critical issue
# ... make changes, commit ...

# Merge to main and tag
git checkout main
git merge hotfix/critical-security-patch --no-ff
git tag -a v1.2.1 -m "Security hotfix 1.2.1"
git push origin main --tags

# Cherry-pick to staging and develop
git checkout staging
git cherry-pick <commit-hash>
git push origin staging

git checkout develop
git cherry-pick <commit-hash>
git push origin develop

# Delete hotfix branch
git branch -d hotfix/critical-security-patch
git push origin --delete hotfix/critical-security-patch
```

## Branch Naming Conventions

Follow these naming patterns for consistency:

```
feature/PROJ-123-short-description     # New features
fix/PROJ-456-bug-description           # Bug fixes for staging
hotfix/critical-issue-description      # Critical production fixes
release/v1.2.0                         # Release preparation
```

**Examples:**
- `feature/AUTH-101-oauth-google-integration`
- `feature/UI-202-dark-mode-support`
- `fix/STOR-303-file-upload-timeout`
- `hotfix/security-jwt-validation`
- `release/v2.0.0`

## Coding Conventions

### Python Services (Backend)

- **Style Guide**: Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- **Linting**: Use `flake8` and `black` for code formatting
- **Type Hints**: Use type hints where applicable (Python 3.13+)
- **Docstrings**: Use Google-style docstrings

```python
def create_user(username: str, email: str, password: str) -> User:
    """Create a new user in the system.
    
    Args:
        username: The unique username for the user.
        email: The user's email address.
        password: The plain-text password (will be hashed).
    
    Returns:
        The created User object.
    
    Raises:
        ValueError: If username or email already exists.
    """
    # Implementation
    pass
```

**Formatting:**
```bash
# Format code with black
cd services/auth_service
black app/

# Check with flake8
flake8 app/
```

### TypeScript/Next.js (Frontend)

- **Style Guide**: Follow [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)
- **Linting**: ESLint with Next.js configuration
- **Formatting**: Prettier
- **TypeScript**: Strict mode enabled

```typescript
interface User {
  id: string;
  username: string;
  email: string;
}

export async function createUser(
  username: string,
  email: string,
  password: string
): Promise<User> {
  // Implementation
}
```

**Formatting:**
```bash
cd web
npm run lint
npm run format
```

### General Conventions

- **File Names**: 
  - Python: `snake_case.py`
  - TypeScript/React: `PascalCase.tsx` (components), `camelCase.ts` (utilities)
- **Constants**: `UPPER_CASE_WITH_UNDERSCORES`
- **Private Functions**: Prefix with underscore in Python (`_private_function`)
- **API Routes**: Use kebab-case (`/api/auth/login`, `/api/users/create`)

## Commit Message Guidelines

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Changes that don't affect the meaning of the code (formatting, etc.)
- **refactor**: Code change that neither fixes a bug nor adds a feature
- **perf**: Performance improvement
- **test**: Adding or correcting tests
- **chore**: Changes to build process, tooling, dependencies

### Scopes

Use the service or component name:
- `auth` - Auth service
- `identity` - Identity service
- `guardian` - Guardian service
- `project` - Project service
- `basic-io` - Basic IO service
- `storage` - Storage service
- `web` - Frontend
- `tests` - Test suite
- `ci` - CI/CD
- `docker` - Docker configuration

### Examples

```
feat(auth): add OAuth2 Google integration

Implement Google OAuth2 authentication flow with support for
automatic user creation on first login.

Closes #123
```

```
fix(storage): resolve file upload timeout for large files

Increase timeout to 5 minutes and add chunked upload support
for files larger than 100MB.

Fixes #456
```

```
docs(readme): update installation instructions

Add Docker Compose quick start section and clarify
Python version requirements.
```

```
chore(deps): upgrade Flask to 3.1.0

Update all services to use Flask 3.1.0 for security patches.
```

## Pull Request Process

### Before Submitting

1. **Update your branch** with the latest changes from the target branch
2. **Run tests** locally and ensure they pass
3. **Run linters** and fix any issues
4. **Update documentation** if needed
5. **Test manually** in your local environment

### PR Checklist

- [ ] Branch follows naming conventions
- [ ] Commits follow commit message guidelines
- [ ] All tests pass locally
- [ ] Code follows project coding conventions
- [ ] Documentation updated (if applicable)
- [ ] No merge conflicts with target branch
- [ ] PR description clearly explains changes
- [ ] Related issue(s) linked

### PR Template

Use this template when creating a PR:

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix (fix/*)
- [ ] New feature (feature/*)
- [ ] Breaking change
- [ ] Documentation update

## Related Issue(s)
Closes #123
Fixes #456

## How Has This Been Tested?
Describe the tests you ran and the results

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] My code follows the project's coding conventions
- [ ] I have performed a self-review of my code
- [ ] I have commented my code where necessary
- [ ] I have updated the documentation accordingly
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix/feature works
- [ ] New and existing tests pass locally
- [ ] Any dependent changes have been merged
```

### Review Process

1. **Create PR** with a clear title and description
2. **Automated checks** must pass (CI/CD, linting, tests)
3. **Code review** by at least one maintainer
4. **Address feedback** and push updates
5. **Approval** from maintainer(s)
6. **Merge** by maintainer (squash or merge commit based on context)

### Merge Strategies

- **Feature branches**: Squash and merge (clean history)
- **Release branches**: Merge commit (preserve release history)
- **Hotfix branches**: Merge commit (preserve fix details)

## Testing Requirements

All contributions must include appropriate tests.

### Backend Tests (Python)

```bash
# Run service-specific tests
cd services/auth_service
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

**Test Types:**
- Unit tests for business logic
- Integration tests for API endpoints
- Database tests for models

### Frontend Tests (TypeScript)

```bash
cd web
npm test                 # Run all tests
npm run test:watch       # Watch mode
npm run test:coverage    # With coverage
```

**Test Types:**
- Component tests (Jest + React Testing Library)
- Integration tests
- E2E tests (Playwright)

### E2E Tests

```bash
# Run complete E2E test suite
./scripts/run-tests.sh

# Manual execution
cd tests
pytest -v api/
pytest -v ui/
```

### Coverage Requirements

- **Minimum coverage**: 80% for new code
- **Critical paths**: 100% coverage required

## Environment Setup

### Prerequisites

- Python 3.13+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL 16
- Git

### Local Development Setup

```bash
# Clone the repository
git clone git@github.com:bengeek06/waterfall.git
cd waterfall

# Initialize submodules
git submodule update --init --recursive

# Backend services
./scripts/run-backend.sh

# Frontend (separate terminal)
cd web
npm install
npm run dev

# E2E tests (separate terminal)
cd tests
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

See [README.md](README.md) for detailed setup instructions.

## Getting Help

- **Documentation**: Check the [README.md](README.md)
- **Issues**: Search existing issues or create a new one
- **Discussions**: Use GitHub Discussions for questions
- **Email**: Contact maintainers at [benjamin@waterfall-project.pro](mailto:benjamin@waterfall-project.pro)

## Recognition

Contributors are recognized in:
- GitHub contributors page
- Release notes (for significant contributions)
- Project documentation

Thank you for contributing to Waterfall! 🎉
