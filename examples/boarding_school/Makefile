
database:
	createdb school-demo

virtualenv:
	virtualenv .boarding-school

install-packages:
	.boarding-school/bin/pip install -e ../..

load-data:
	./manage.py syncdb
	./manage.py loaddata schools
	./manage.py loaddata --schema hamilton hamilton
	./manage.py loaddata --schema naracoorte_hs naracoorte_hs

clean:
	dropdb school-demo
	rm -rf .boarding-school

runserver:
	./manage.py runserver ${PORT}

sync-unattended:
	./manage.py syncdb --noinput

test:
	DJANGO_SETTINGS_MODULE=settings django-admin.py migrate

all: database virtualenv install-packages load-data
unattended: database sync-unattended load-data