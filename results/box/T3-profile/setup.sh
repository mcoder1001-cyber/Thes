#!/bin/bash
# Build the grid's jar with the CRaC JDK and extract it (as D1's setup.sh), into /var/tmp/grid/app.
set -euo pipefail
cd "$(dirname "$0")/app"
JAVA_HOME=/opt/crac mvn -q -B package -DskipTests
rm -rf /var/tmp/grid/app && mkdir -p /var/tmp/grid
/opt/crac/bin/java -Djarmode=tools -jar target/craca.jar extract --destination /var/tmp/grid/app
