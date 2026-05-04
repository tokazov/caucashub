# CaucasHub Makefile — утилиты разработки
# Использование: make <target>

.PHONY: check-deps test lint deploy-check

## check-deps: Проверить совместимость зависимостей (запускать перед коммитом)
check-deps:
	@echo "🔍 Checking dependency compatibility..."
	@pip install -r requirements.txt --dry-run --quiet 2>&1 | grep -E "ERROR|conflict|Cannot install" || echo "✅ Dependencies OK"
	@python3 -c "\
import importlib, sys;\
pkgs = ['fastapi','sqlalchemy','passlib','bcrypt','httpx','pydantic','alembic','google'];\
failed=[];\
[failed.append(p) or print(f'  ❌ {p}') for p in pkgs if importlib.util.find_spec(p.replace('.','_') if '.' in p else p) is None];\
sys.exit(1) if failed else print('✅ All key packages importable')"

## test: Запустить тесты (основные, без port-конфликтов)
test:
	python3 -m pytest tests/test_adr013_contacts.py tests/test_subscriptions_e1.py tests/test_subscriptions_e2.py tests/test_transport_e2.py tests/test_transport_e3.py tests/test_pagination.py -v --tb=short -q

## lint: Проверить код через ruff
lint:
	python3 -m ruff check app/

## deploy-check: Полная проверка перед деплоем
deploy-check: lint check-deps
	@echo "🚀 Running pre-deploy checks..."
	python3 -c "from app.main import app; print('✅ App imports OK')"
	python3 -m pytest tests/test_adr013_contacts.py tests/test_pagination.py -q --tb=short
	@echo "✅ deploy-check passed"

## help: Показать доступные команды
help:
	@grep -E '^## ' Makefile | sed 's/## //'
