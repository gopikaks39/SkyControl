// SkyControl CI/CD pipeline: checkout -> lint + tests (in Docker) -> image -> container smoke test -> deploy.
// The agent only needs the Docker CLI and curl; Python runs inside containers (see jenkins/ for a ready Jenkins).
// Works whether SkyControl is the repository root or the SkyControl/ folder of a larger repository.
// Plugins: Pipeline, Git, JUnit, Credentials Binding (all in the "suggested plugins" set).
// Credentials (Manage Jenkins > Credentials, kind "Secret text"):
//   skycontrol-controller-password, skycontrol-supervisor-password
pipeline {
    agent any

    options {
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    parameters {
        booleanParam(name: 'DEPLOY', defaultValue: true, description: 'Deploy with Docker after a green build')
    }

    environment {
        IMAGE = 'skycontrol'
        SMOKE_PORT = '5099'
        APP_PORT = '5000'
        // Where the agent reaches published container ports: 127.0.0.1 on a normal agent,
        // host.docker.internal when Jenkins itself runs in Docker (see jenkins/docker-compose.yml).
        TARGET_HOST = "${env.SKYCONTROL_TARGET_HOST ?: '127.0.0.1'}"
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    try {
                        checkout scm
                    } catch (err) {
                        echo "No SCM attached to this job (${err.message}); building the workspace as it is."
                    }
                    env.APP_DIR = fileExists('run.py') ? '.' : 'SkyControl'
                    env.REPORTS = env.APP_DIR == '.' ? 'reports' : 'SkyControl/reports'
                    env.GIT_SHORT = sh(script: 'git rev-parse --short HEAD 2>/dev/null || echo local', returnStdout: true).trim()
                }
                echo "Building SkyControl from '${env.APP_DIR}' at ${env.GIT_SHORT}"
            }
        }

        stage('Lint and tests') {
            steps {
                dir(env.APP_DIR) {
                    sh '''
                        docker build --target test -t ${IMAGE}-test:${BUILD_NUMBER} .
                        docker rm -f skycontrol-tests >/dev/null 2>&1 || true
                        rm -rf reports
                        set +e
                        docker run --name skycontrol-tests ${IMAGE}-test:${BUILD_NUMBER}
                        status=$?
                        set -e
                        docker cp skycontrol-tests:/app/reports ./reports || true
                        docker rm -f skycontrol-tests >/dev/null 2>&1 || true
                        exit $status
                    '''
                }
            }
            post {
                always {
                    junit testResults: "${env.REPORTS}/junit.xml", allowEmptyResults: true
                }
            }
        }

        stage('Build image') {
            steps {
                dir(env.APP_DIR) {
                    sh 'docker build --target runtime -t ${IMAGE}:${BUILD_NUMBER} -t ${IMAGE}:${GIT_SHORT} -t ${IMAGE}:latest .'
                }
            }
        }

        stage('Smoke test container') {
            steps {
                withCredentials([string(credentialsId: 'skycontrol-controller-password', variable: 'SKYCONTROL_CONTROLLER_PASSWORD'),
                                 string(credentialsId: 'skycontrol-supervisor-password', variable: 'SKYCONTROL_SUPERVISOR_PASSWORD')]) {
                    dir(env.APP_DIR) {
                        sh '''
                            docker rm -f skycontrol-smoke >/dev/null 2>&1 || true
                            docker run -d --name skycontrol-smoke -p ${SMOKE_PORT}:5000 \
                                -e SKYCONTROL_CONTROLLER_PASSWORD -e SKYCONTROL_SUPERVISOR_PASSWORD ${IMAGE}:${BUILD_NUMBER}
                            for i in $(seq 1 30); do
                                curl -fs http://${TARGET_HOST}:${SMOKE_PORT}/api/health && break
                                sleep 2
                            done
                            sh scripts/smoke_test.sh http://${TARGET_HOST}:${SMOKE_PORT} supervisor "$SKYCONTROL_SUPERVISOR_PASSWORD"
                        '''
                    }
                }
            }
            post {
                always { sh 'docker rm -f skycontrol-smoke >/dev/null 2>&1 || true' }
            }
        }

        stage('Deploy') {
            when { expression { return params.DEPLOY } }
            steps {
                withCredentials([string(credentialsId: 'skycontrol-controller-password', variable: 'SKYCONTROL_CONTROLLER_PASSWORD'),
                                 string(credentialsId: 'skycontrol-supervisor-password', variable: 'SKYCONTROL_SUPERVISOR_PASSWORD')]) {
                    dir(env.APP_DIR) {
                        sh '''
                            docker rm -f skycontrol >/dev/null 2>&1 || true
                            docker run -d --name skycontrol --restart unless-stopped -p ${APP_PORT}:5000 \
                                -v skycontrol-db:/app/data/db \
                                -e SKYCONTROL_CONTROLLER_PASSWORD -e SKYCONTROL_SUPERVISOR_PASSWORD ${IMAGE}:latest
                            for i in $(seq 1 30); do
                                curl -fs http://${TARGET_HOST}:${APP_PORT}/api/health && break
                                sleep 2
                            done
                            docker ps --filter name=skycontrol
                        '''
                    }
                }
                echo "SkyControl ${env.GIT_SHORT} deployed on port ${env.APP_PORT}"
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: "${env.REPORTS}/**", allowEmptyArchive: true
        }
        success { echo "SkyControl build ${env.BUILD_NUMBER} passed every stage." }
        failure { echo 'SkyControl pipeline failed: open the failed stage log.' }
    }
}
