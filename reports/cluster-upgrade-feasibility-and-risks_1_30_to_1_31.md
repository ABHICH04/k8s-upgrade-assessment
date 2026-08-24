# Kubernetes Upgrade Feasibility, Compatibility, and Risk Assessment

_Generated: 2026-08-03 07:20:14 UTC_
_Mode: local evidence-based analyzer_
_kubectl context cluster (detected server): `1.30.14-eks-8f14419`_

## Executive Summary

```text
UPGRADE DECISION:
NOT RECOMMENDED

SOURCE VERSION:
1.30

TARGET VERSION:
1.31

READINESS SCORE:
7/100

CONFIDENCE:
80%

CRITICAL ISSUES:
- ingress-nginx image not supported for k8s 1.31: Official support matrix lists v1.6.4 for k8s 1.23–1.26 only. Upgrade to >=1.11 / 1.12+ for 1.30/1.31.
- rancher-agent image not supported for k8s 1.31: Rancher 2.8.x supports up to Kubernetes 1.28. 1.30+ needs Rancher 2.9+; 1.31 typically needs newer Rancher (2.10+ depending on matrix).
- rancher-webhook image not supported for k8s 1.31: Tied to Rancher 2.8 line; upgrade with Rancher manager/agent before target k8s.
- fleet-agent image not supported for k8s 1.31: Fleet agent version aligned with Rancher 2.8; verify against Rancher upgrade path.
- aws-fsx-openzfs-csi-driver image not supported for k8s 1.31: FSx OpenZFS CSI sidecars labeled eks-1-26-latest — high risk on 1.30 already; must upgrade before 1.31.

HIGH RISKS:
- keda: KEDA 2.13 targeted older k8s lines; upgrade to a 2.15+/2.16+ release validated for 1.30/1.31 before or immediately after control-plane upgrade.
- stackgres: StackGres 1.15 installed with Fail-policy webhooks — vendor k8s compatibility must be confirmed; treat as risk until verified.
- spark-operator: Spark operator 2.4 with Fail webhooks on SparkApplication — confirm Kubeflow spark-operator support for target k8s.
- aws-ebs-csi-driver: EBS CSI images tagged with eks-1-30 sidecars. Upgrade EKS addon to the 1.31-compatible build during/after control-plane upgrade.
- aws-efs-csi-driver: EFS CSI v2.0.4 with eks-1-29 sidecars — bump addon before or with node/control-plane upgrade to 1.31.
- kube-proxy: kube-proxy is pinned to 1.30 — must be upgraded with the EKS control plane / addon to 1.31.
- Cordoned/SchedulingDisabled node(s) reduce upgrade capacity: ip-10-0-29-18.ap-south-1.compute.internal
- Node memory pressure may cause eviction during drain: ip-10-0-63-213.ap-south-1.compute.internal memory 85%
- 9 webhook config(s) use failurePolicy=Fail — operator downtime can block admissions
- Nodes run Bottlerocket aws-k8s-1.30; must roll to aws-k8s-1.31 AMI/nodegroup after control plane upgrade.

WARNINGS:
- StorageClass uses in-tree provisioner kubernetes.io/aws-ebs (gp2/gp3). Rely on CSI migration / ebs.csi.aws.com; validate volumes after upgrade.
- OpenEBS NFS StorageClass present — confirm operator/CSI compatibility with target k8s.
- 14 CRD(s) use conversion webhooks — webhook outage can break multi-version reads.
- 19 CRD(s) store alpha versions — higher schema/compat risk across upgrades.

REQUIRED ACTIONS BEFORE UPGRADE:
1. Upgrade only one minor version at a time (EKS 1.30 → 1.31).
2. Upgrade ingress-nginx from v1.6.4 to a release tested on Kubernetes 1.31 (e.g. 1.11+/1.12+).
3. Upgrade Rancher (manager + cattle-cluster-agent/webhook/fleet) to a version that supports Kubernetes 1.31 before or as a gate for the cluster upgrade.
4. Upgrade KEDA to a release validated for 1.30/1.31.
5. Upgrade FSx OpenZFS CSI and EFS CSI addons/sidecars off eks-1-26 / eks-1-29 builds.
6. Confirm StackGres + Spark-operator vendor support matrices for 1.31; plan operator bumps if unsupported.
7. Uncordon or replace SchedulingDisabled node and free memory on high-pressure nodes before node rolling.
8. Take backups (etcd via EKS snapshot/restore plan, StackGres/Postgres, Kafka topics, PV snapshots where applicable).

RECOMMENDED UPGRADE ORDER:
1. Backup + change freeze for critical namespaces
2. Upgrade Rancher management components (if used to administer this EKS cluster)
3. Upgrade ingress-nginx, KEDA, FSx/EFS CSI, StackGres/Spark-operator as required
4. Upgrade EKS control plane 1.30 → 1.31
5. Upgrade EKS addons (vpc-cni, coredns, kube-proxy, ebs-csi) to 1.31 builds
6. Roll Bottlerocket nodegroup to aws-k8s-1.31 AMI (one node at a time)
7. Validate workloads, webhooks, ingress, storage, Kafka/Postgres/Spark

POST-UPGRADE VALIDATIONS:
1. kubectl get nodes — all Ready on v1.31.x
2. kubectl get apiservices — all Available=True
3. kubectl get pods -A — no CrashLoopBackOff on operators/webhooks
4. Test ingress HTTP(S) path through ingress-nginx
5. Create/delete a PVC on gp3 and efs-sc; confirm attach
6. cert-manager Certificate ready; KEDA ScaledObject reconcile
7. StackGres/Strimzi/Spark operator health + sample reconcile
8. Rancher UI/cluster-agent connected

FINAL RECOMMENDATION:
Do not upgrade to 1.31 until ingress-nginx and Rancher-line components are brought into a supported matrix. EKS control-plane upgrade itself is manageable, but unsupported ingress and Rancher agents plus lagging CSI sidecars create verified outage/management risks. Treat decision as NOT RECOMMENDED.
```

## Issue Classification

### Verified Issues
- Cluster server is EKS `v1.30.x` with Bottlerocket `aws-k8s-1.30` workers.
- ingress-nginx `v1.6.4` is outside upstream supported k8s versions for 1.30/1.31.
- Rancher agent `v2.8.3` / webhook `v0.4.18` are from a Rancher line that only certified through k8s 1.28.
- FSx OpenZFS CSI sidecars reference `eks-1-26-latest`; EFS CSI sidecars reference `eks-1-29`.
- Multiple admission webhooks use `failurePolicy=Fail` (cert-manager, ingress-nginx, rancher, spark, stackgres).
- One worker is `SchedulingDisabled`; at least one node shows high memory utilization.

### Probable Issues
- KEDA 2.13.x may misbehave or be unsupported on 1.31.
- StackGres / Spark-operator Fail webhooks can block DB/Spark CR changes if operators crash after upgrade.
- In-tree `kubernetes.io/aws-ebs` StorageClasses depend on CSI migration remaining healthy.

### Possible Issues
- Prometheus-operator / Grafana stack subtle scrape/API changes.
- OpenEBS NFS provisioner edge cases during node drains.

### Unknown Risks
- Full vendor matrices for StackGres 1.15 and Spark-operator 2.4 vs k8s 1.31 not confirmed from cluster metadata alone.
- Custom/internal images (e.g. `quarticai/stackgres-proxy`) behavior unknown.
- Collection gaps (if any) listed at the end reduce confidence.

## Step 1 — Cluster Information

```text
Client Version: v1.35.0
Kustomize Version: v5.7.1
Server Version: v1.30.14-eks-8f14419
```

```text
Kubernetes control plane is running at https://rancher.quartic.ai/k8s/clusters/c-m-wdnjb6qw
CoreDNS is running at https://rancher.quartic.ai/k8s/clusters/c-m-wdnjb6qw/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

To further debug and diagnose cluster problems, use 'kubectl cluster-info dump'.
```

**Nodes**
```text
NAME                                         STATUS                     ROLES    AGE    VERSION                INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                                KERNEL-VERSION   CONTAINER-RUNTIME
ip-10-0-29-18.ap-south-1.compute.internal    Ready,SchedulingDisabled   <none>   165d   v1.30.10-eks-1a9dacd   10.0.29.18    <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
ip-10-0-63-213.ap-south-1.compute.internal   Ready                      <none>   165d   v1.30.10-eks-1a9dacd   10.0.63.213   <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
ip-10-0-7-113.ap-south-1.compute.internal    Ready                      <none>   154d   v1.30.10-eks-1a9dacd   10.0.7.113    <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
```

- Managed platform: **Amazon EKS** (accessed via Rancher API proxy)
- Detected API server version: `1.30.14-eks-8f14419`
- Worker OS: Bottlerocket `aws-k8s-1.30` / containerd (from node listing)
- HA workers observed: 3 nodes (1 SchedulingDisabled)

## Step 2 — Resource Inventory

Namespaces:
```text
NAME                          STATUS   AGE
cattle-fleet-system           Active   446d
cattle-impersonation-system   Active   446d
cattle-system                 Active   446d
cert-manager                  Active   236d
default                       Active   446d
kube-node-lease               Active   446d
kube-public                   Active   446d
kube-system                   Active   446d
local                         Active   446d
logging                       Active   320d
monitoring                    Active   438d
```

Deployments (excerpt / full collect stored in snapshot):
```text
NAMESPACE             NAME                                  READY   UP-TO-DATE   AVAILABLE   AGE    CONTAINERS                                                                           IMAGES                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      SELECTOR
cattle-fleet-system   fleet-agent                           1/1     1            1           446d   fleet-agent                                                                          rancher/fleet-agent:v0.9.17                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 app=fleet-agent
cattle-system         cattle-cluster-agent                  2/2     2            2           446d   cluster-register                                                                     rancher/rancher-agent:v2.8.3                                                                                                                                                                                                                                                                                                                                                                                                                                                                                app=cattle-cluster-agent
cattle-system         rancher-webhook                       1/1     1            1           446d   rancher-webhook                                                                      rancher/rancher-webhook:v0.4.18                                                                                                                                                                                                                                                                                                                                                                                                                                                                             app=rancher-webhook
cert-manager          cert-manager                          1/1     1            1           236d   cert-manager-controller                                                              quay.io/jetstack/cert-manager-controller:v1.15.2                                                                                                                                                                                                                                                                                                                                                                                                                                                            app.kubernetes.io/component=controller,app.kubernetes.io/instance=cert-manager,app.kubernetes.io/name=cert-manager
cert-manager          cert-manager-cainjector               1/1     1            1           236d   cert-manager-cainjector                                                              quay.io/jetstack/cert-manager-cainjector:v1.15.2                                                                                                                                                                                                                                                                                                                                                                                                                                                            app.kubernetes.io/component=cainjector,app.kubernetes.io/instance=cert-manager,app.kubernetes.io/name=cainjector
cert-manager          cert-manager-webhook                  1/1     1            1           236d   cert-manager-webhook                                                                 quay.io/jetstack/cert-manager-webhook:v1.15.2                                                                                                                                                                                                                                                                                                                                                                                                                                                               app.kubernetes.io/component=webhook,app.kubernetes.io/instance=cert-manager,app.kubernetes.io/name=webhook
default               airflow-api-server                    1/1     1            1           245d   api-server                                                                           quarticai/mvda-airflow:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                              component=api-server,release=airflow,tier=airflow
default               airflow-dag-processor                 1/1     1            1           11d    dag-processor,dag-processor-log-groomer                                              quarticai/mvda-airflow:debug9390-1,quarticai/mvda-airflow:debug9390-1                                                                                                                                                                                                                                                                                                                                                                                                                                       component=dag-processor,release=airflow,tier=airflow
default               airflow-scheduler                     1/1     1            1           11d    scheduler,airflow-scheduler-monitor,scheduler-log-groomer                            quarticai/mvda-airflow:debug9390-1,quarticai/mvda-airflow:debug9390-1,quarticai/mvda-airflow:debug9390-1                                                                                                                                                                                                                                                                                                                                                                                                    component=scheduler,release=airflow,tier=airflow
default               airflow-statsd                        1/1     1            1           245d   statsd                                                                               quay.io/prometheus/statsd-exporter:v0.28.0                                                                                                                                                                                                                                                                                                                                                                                                                                                                  component=statsd,release=airflow,tier=airflow
default               blackbox-exporter                     1/1     1            1           237d   blackbox-exporter-container-0                                                        prom/blackbox-exporter:v0.25.0                                                                                                                                                                                                                                                                                                                                                                                                                                                                              app=blackbox-exporter
default               celery                                3/3     3            3           446d   celery                                                                               quarticai/celery-async-tasks:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                        app=celery,tier=celery
default               copy-tags-job                         1/1     1            1           436d   copy-tags-job                                                                        quarticai/powergauge:copy-job                                                                                                                                                                                                                                                                                                                                                                                                                                                                               app=copy-tags-job
default               cube-api                              1/1     1            1           445d   cube                                                                                 quarticai/cube:1.2.29                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       app.kubernetes.io/component=api,app.kubernetes.io/instance=cube,app.kubernetes.io/name=cube
default               cube-worker                           1/1     1            1           445d   cube                                                                                 quarticai/cube:1.2.29                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       app.kubernetes.io/component=worker,app.kubernetes.io/instance=cube,app.kubernetes.io/name=cube
default               external-batch-polling                1/1     1            1           12d    external-batch-polling                                                               quarticai/external-batch-polling:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                    app=external-batch-polling
default               frontend                              1/1     1            1           446d   frontend                                                                             quarticai/frontend:QPD-9709                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 app.kubernetes.io/component=deployment,app.kubernetes.io/name=frontend
default               graphql                               1/1     1            1           446d   graphql                                                                              quarticai/graphql_server:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                            app=graphql
default               heartbeat                             0/0     0            0           446d   heartbeat                                                                            quarticprod/qpro-heartbeat:2.0.1                                                                                                                                                                                                                                                                                                                                                                                                                                                                            app.kubernetes.io/component=deployment,app.kubernetes.io/name=heartbeat
default               ingress-nginx-controller              1/1     1            1           446d   controller                                                                           registry.k8s.io/ingress-nginx/controller:v1.6.4@sha256:15be4666c53052484dd2992efacf2f50ea77a78ae8aa21ccd91af6baaa7ea22f                                                                                                                                                                                                                                                                                                                                                                                     app.kubernetes.io/component=controller,app.kubernetes.io/instance=ingress,app.kubernetes.io/name=ingress-nginx
default               jupyterhub                            1/1     1            1           446d   jupyterhub                                                                           quarticai/jupyterhub:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                app=jupyterhub,tier=jupyterhub
default               keda-admission-webhooks               1/1     1            1           446d   keda-admission-webhooks                                                              ghcr.io/kedacore/keda-admission-webhooks:2.13.1                                                                                                                                                                                                                                                                                                                                                                                                                                                             app=keda-admission-webhooks
default               keda-operator                         1/1     1            1           446d   keda-operator                                                                        ghcr.io/kedacore/keda:2.13.1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                app=keda-operator
default               keda-operator-metrics-apiserver       1/1     1            1           446d   keda-operator-metrics-apiserver                                                      ghcr.io/kedacore/keda-metrics-apiserver:2.13.1                                                                                                                                                                                                                                                                                                                                                                                                                                                              app=keda-operator-metrics-apiserver
default               knowledgebase                         1/1     1            1           446d   knowledgebase                                                                        quarticai/kb-docusaurus:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                             app=knowledgebase
default               luigi                                 1/1     1            1           446d   luigi                                                                                quarticai/luigi:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     app=luigi,tier=luigi
default               mlflow                                1/1     1            1           446d   mlflow                                                                               quarticai/mlflow:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    app=mlflow
default               mvda-app                              0/0     0            0           446d   mvda-app                                                                             quarticai/mvda-django:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                               app=mvda-app
default               mvda-graphql                          1/1     1            1           432d   mvda-graphql                                                                         quarticai/mvda-graphql-server:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                       app=mvda-graphql
default               piqlite1                              1/1     1            1           236d   piqlite1                                                                             quarticai/quartic_edge_suite:k8s                                                                                                                                                                                                                                                                                                                                                                                                                                                                            app=piqlite1
default               postgres-exporter                     1/1     1            1           237d   prometheus-postgres-exporter                                                         quay.io/ongres/prometheus-postgres-exporter:v0.12.1-build-6.31                                                                                                                                                                                                                                                                                                                                                                                                                                              app=postgres-exporter
default               quartic-scripts                       1/1     1            1           446d   quartic-scripts                                                                      quarticai/contexalyze-scripts:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                       app=quartic-scripts
default               slack-mention-bot                     1/1     1            1           11d    bot                                                                                  quarticai/slack-bot-tagging:8.1                                                                                                                                                                                                                                                                                                                                                                                                                                                                             app=slack-mention-bot
default               spark-operator-controller             1/1     1            1           227d   spark-operator-controller                                                            ghcr.io/kubeflow/spark-operator/controller:2.4.0                                                                                                                                                                                                                                                                                                                                                                                                                                                            app.kubernetes.io/component=controller,app.kubernetes.io/instance=spark-operator,app.kubernetes.io/name=spark-operator
default               spark-operator-webhook                1/1     1            1           227d   spark-operator-webhook                                                               ghcr.io/kubeflow/spark-operator/controller:2.4.0                                                                                                                                                                                                                                                                                                                                                                                                                                                            app.kubernetes.io/component=webhook,app.kubernetes.io/instance=spark-operator,app.kubernetes.io/name=spark-operator
default               stackgres-operator                    1/1     1            1           446d   stackgres-operator                                                                   quay.io/stackgres/operator:1.15.0                                                                                                                                                                                                                                                                                                                                                                                                                                                                           app=stackgres-operator,group=stackgres.io
default               stackgres-proxy                       1/1     1            1           432d   nginx                                                                                quarticai/stackgres-proxy:latest                                                                                                                                                                                                                                                                                                                                                                                                                                                                            app=stackgres-proxy
default               stackgres-restapi                     1/1     1            1           446d   stackgres-restapi,stackgres-adminui                                                  quay.io/stackgres/restapi:1.15.0,quay.io/stackgres/admin-ui:1.15.0                                                                                                                                                                                                                                                                                                                                                                                                                                          app=StackGresConfig,stackgres.io/config-name=stackgres-operator,stackgres.io/config-uid=0332b06e-ec35-4f71-b4a2-012afec0be7f,stackgres.io/restapi=true
default               strimzi-cluster-entity-operator       1/1     1            1           166d   topic-operator,user-operator                                                         quay.io/strimzi/operator:0.50.0,quay.io/strimzi/operator:0.50.0                                                                                                                                                                                                                                                                                                                                                                                                                                             strimzi.io/cluster=strimzi-cluster,strimzi.io/kind=Kafka,strimzi.io/name=strimzi-cluster-entity-operator
default               strimzi-cluster-operator              1/1     1            1           439d   strimzi-cluster-operator                                                             quay.io/strimzi/operator:0.50.0                                                                                                                                                                                                                                                                                                                                                                                                                                                                             name=strimzi-cluster-operator,strimzi.io/kind=cluster-operator
default               test-reg-qlite                        1/1     1            1           157d   test-reg-qlite                                                                       quarticai/quartic_edge_suite:k8s                                                                                                                                                                                                                                                                                                                                                                                                                                                                            app=test-reg-qlite
default               websocket                             1/1     1            1           446d   websocket                                                                            quarticai/quartic-websocket:develop                                                                                                                                                                                                                                                                                                                                                                                                                                                                         app=websocket
kube-system           coredns                               2/2     2            2           446d   coredns                                                                              602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/coredns:v1.11.4-eksbuild.2                                                                                                                                                                                                                                                                                                                                                                                                                                eks.amazonaws.com/component=coredns,k8s-app=kube-dns
kube-system           ebs-csi-controller                    2/2     2            2           446d   ebs-plugin,csi-provisioner,csi-attacher,csi-snapshotter,csi-resizer,liveness-probe   602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/aws-ebs-csi-driver:v1.31.0,602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/csi-provisioner:v4.0.1-eks-1-30-4,602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/csi-attacher:v4.5.1-eks-1-30-4,602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/csi-snapshotter:v7.0.2-eks-1-30-4,602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/csi-resizer:v1.10.1-eks-1-30-4,602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/livenessprobe:v2.12.0-eks-1-30-4   app=ebs-csi-controller,app.kubernetes.io/name=aws-ebs-csi-driver
kube-system           efs-csi-controller                    2/2     2            2           446d   efs-plugin,csi-provisioner,liveness-probe                                            public.ecr.aws/efs-csi-driver/amazon/aws-efs-csi-driver:v2.0.4,public.ecr.aws/eks-distro/kubernetes-csi/external-provisioner:v4.0.0-eks-1-29-7,public.ecr.aws/eks-distro/kubernetes-csi/livenessprobe:v2.12.0-eks-1-29-7                                                                                                                                                                                                                                                                                    app=efs-csi-controller,app.kubernetes.io/instance=aws-efs-csi-driver,app.kubernetes.io/name=aws-efs-csi-driver
kube-system           fsx-openzfs-csi-controller            2/2     2            2           234d   fsx-openzfs-plugin,csi-provisioner,csi-snapshotter,csi-resizer,liveness-probe        public.ecr.aws/fsx-csi-driver/aws-fsx-openzfs-csi-driver:v1.2.0,public.ecr.aws/eks-distro/kubernetes-csi/external-provisioner:v3.4.0-eks-1-26-latest,public.ecr.aws/eks-distro/kubernetes-csi/external-snapshotter/csi-snapshotter:v6.2.1-eks-1-26-latest,public.ecr.aws/eks-distro/kubernetes-csi/external-resizer:v1.7.0-eks-1-26-latest,public.ecr.aws/eks-distro/kubernetes-csi/livenessprobe:v2.9.0-eks-1-26-latest                                                                                    app.kubernetes.io/name=fsx-openzfs-csi-controller,app.kubernetes.io/part-of=aws-fsx-openzfs-csi-driver
kube-system           metrics-server                        1/1     1            1           446d   metrics-server                                                                       registry.k8s.io/metrics-server/metrics-server:v0.7.1                                                                                                                                                                                                                                                                                                                                                                                                                                                        app.kubernetes.io/instance=metrics-server,app.kubernetes.io/name=metrics-server
monitoring            checkpoint-monitor                    1/1     1            1           153d   monitor                                                                              bitnami/kubectl:latest                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      app=checkpoint-monitor
monitoring            prometheus-grafana                    1/1     1            1           237d   grafana-sc-dashboard,grafana-sc-datasources,grafana                                  quay.io/kiwigrid/k8s-sidecar:1.30.10,quay.io/kiwigrid/k8s-sidecar:1.30.10,docker.io/grafana/grafana:12.1.1                                                                                                                                                                                                                                                                                                                                                                                                  app.kubernetes.io/instance=prometheus,app.kubernetes.io/name=grafana
monitoring            prometheus-kube-prometheus-operator   1/1     1            1           237d   kube-prometheus-stack                                                                quay.io/prometheus-operator/prometheus-operator:v0.85.0                                                                                                                                                                                                                                                                                                                                                                                                                                                     app=kube-prometheus-stack-operator,release=prometheus
monitoring            prometheus-kube-state-metrics         1/1     1            1           237d   kube-state-metrics                                                                   registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.17.0                                                                                                                                                                                                                                                                                                                                                                                                                                               app.kubernetes.io/instance=prometheus,app.kubernetes.io/name=kube-state-metrics
```

## Step 3 — CRD Inventory

Total CRDs: **75**

| CRD | Group | Kind | Served | Storage | Conversion |
| --- | --- | --- | --- | --- | --- |
| alertmanagerconfigs.monitoring.coreos.com | monitoring.coreos.com | AlertmanagerConfig | v1alpha1 | v1alpha1 | None |
| alertmanagers.monitoring.coreos.com | monitoring.coreos.com | Alertmanager | v1 | v1 | None |
| apiservices.management.cattle.io | management.cattle.io | APIService | v3 | v3 | None |
| applicationnetworkpolicies.networking.k8s.aws | networking.k8s.aws | ApplicationNetworkPolicy | v1alpha1 | v1alpha1 | None |
| apps.catalog.cattle.io | catalog.cattle.io | App | v1 | v1 | None |
| authconfigs.management.cattle.io | management.cattle.io | AuthConfig | v3 | v3 | None |
| blockdeviceclaims.openebs.io | openebs.io | BlockDeviceClaim | v1alpha1 | v1alpha1 | None |
| blockdevices.openebs.io | openebs.io | BlockDevice | v1alpha1 | v1alpha1 | None |
| certificaterequests.cert-manager.io | cert-manager.io | CertificateRequest | v1 | v1 | None |
| certificates.cert-manager.io | cert-manager.io | Certificate | v1 | v1 | None |
| challenges.acme.cert-manager.io | acme.cert-manager.io | Challenge | v1 | v1 | None |
| cloudeventsources.eventing.keda.sh | eventing.keda.sh | CloudEventSource | v1alpha1 | v1alpha1 | None |
| clusterissuers.cert-manager.io | cert-manager.io | ClusterIssuer | v1 | v1 | None |
| clusternetworkpolicies.networking.k8s.aws | networking.k8s.aws | ClusterNetworkPolicy | v1alpha1 | v1alpha1 | None |
| clusterpolicyendpoints.networking.k8s.aws | networking.k8s.aws | ClusterPolicyEndpoint | v1alpha1 | v1alpha1 | None |
| clusterregistrationtokens.management.cattle.io | management.cattle.io | ClusterRegistrationToken | v3 | v3 | None |
| clusterrepos.catalog.cattle.io | catalog.cattle.io | ClusterRepo | v1 | v1 | None |
| clusters.management.cattle.io | management.cattle.io | Cluster | v3 | v3 | None |
| clustertriggerauthentications.keda.sh | keda.sh | ClusterTriggerAuthentication | v1alpha1 | v1alpha1 | None |
| cninodes.vpcresources.k8s.aws | vpcresources.k8s.aws | CNINode | v1alpha1 | v1alpha1 | None |
| eniconfigs.crd.k8s.amazonaws.com | crd.k8s.amazonaws.com | ENIConfig | v1alpha1 | v1alpha1 | None |
| features.management.cattle.io | management.cattle.io | Feature | v3 | v3 | None |
| groupmembers.management.cattle.io | management.cattle.io | GroupMember | v3 | v3 | None |
| groups.management.cattle.io | management.cattle.io | Group | v3 | v3 | None |
| issuers.cert-manager.io | cert-manager.io | Issuer | v1 | v1 | None |
| kafkabridges.kafka.strimzi.io | kafka.strimzi.io | KafkaBridge | v1, v1beta2 | v1beta2 | None |
| kafkaconnectors.kafka.strimzi.io | kafka.strimzi.io | KafkaConnector | v1, v1beta2 | v1beta2 | None |
| kafkaconnects.kafka.strimzi.io | kafka.strimzi.io | KafkaConnect | v1, v1beta2 | v1beta2 | None |
| kafkamirrormaker2s.kafka.strimzi.io | kafka.strimzi.io | KafkaMirrorMaker2 | v1, v1beta2 | v1beta2 | None |
| kafkamirrormakers.kafka.strimzi.io | kafka.strimzi.io | KafkaMirrorMaker | v1beta2 | v1beta2 | None |
| kafkanodepools.kafka.strimzi.io | kafka.strimzi.io | KafkaNodePool | v1, v1beta2 | v1beta2 | None |
| kafkarebalances.kafka.strimzi.io | kafka.strimzi.io | KafkaRebalance | v1, v1beta2 | v1beta2 | None |
| kafkas.kafka.strimzi.io | kafka.strimzi.io | Kafka | v1, v1beta2 | v1beta2 | None |
| kafkatopics.kafka.strimzi.io | kafka.strimzi.io | KafkaTopic | v1, v1beta2, v1beta1, v1alpha1 | v1beta2 | None |
| kafkausers.kafka.strimzi.io | kafka.strimzi.io | KafkaUser | v1, v1beta2, v1beta1, v1alpha1 | v1beta2 | None |
| navlinks.ui.cattle.io | ui.cattle.io | NavLink | v1 | v1 | None |
| operations.catalog.cattle.io | catalog.cattle.io | Operation | v1 | v1 | None |
| orders.acme.cert-manager.io | acme.cert-manager.io | Order | v1 | v1 | None |
| podmonitors.monitoring.coreos.com | monitoring.coreos.com | PodMonitor | v1 | v1 | None |
| podsecurityadmissionconfigurationtemplates.management.cattle.io | management.cattle.io | PodSecurityAdmissionConfigurationTemplate | v3 | v3 | None |
| policyendpoints.networking.k8s.aws | networking.k8s.aws | PolicyEndpoint | v1alpha1 | v1alpha1 | None |
| preferences.management.cattle.io | management.cattle.io | Preference | v3 | v3 | None |
| probes.monitoring.coreos.com | monitoring.coreos.com | Probe | v1 | v1 | None |
| prometheusagents.monitoring.coreos.com | monitoring.coreos.com | PrometheusAgent | v1alpha1 | v1alpha1 | None |
| prometheuses.monitoring.coreos.com | monitoring.coreos.com | Prometheus | v1 | v1 | None |
| prometheusrules.monitoring.coreos.com | monitoring.coreos.com | PrometheusRule | v1 | v1 | None |
| scaledjobs.keda.sh | keda.sh | ScaledJob | v1alpha1 | v1alpha1 | None |
| scaledobjects.keda.sh | keda.sh | ScaledObject | v1alpha1 | v1alpha1 | None |
| scheduledsparkapplications.sparkoperator.k8s.io | sparkoperator.k8s.io | ScheduledSparkApplication | v1beta2 | v1beta2 | None |
| scrapeconfigs.monitoring.coreos.com | monitoring.coreos.com | ScrapeConfig | v1alpha1 | v1alpha1 | None |
| securitygrouppolicies.vpcresources.k8s.aws | vpcresources.k8s.aws | SecurityGroupPolicy | v1beta1 | v1beta1 | None |
| servicemonitors.monitoring.coreos.com | monitoring.coreos.com | ServiceMonitor | v1 | v1 | None |
| settings.management.cattle.io | management.cattle.io | Setting | v3 | v3 | None |
| sgbackups.stackgres.io | stackgres.io | SGBackup | v1 | v1 | Webhook |
| sgclusters.stackgres.io | stackgres.io | SGCluster | v1 | v1 | Webhook |
| sgconfigs.stackgres.io | stackgres.io | SGConfig | v1 | v1 | Webhook |
| sgdbops.stackgres.io | stackgres.io | SGDbOps | v1 | v1 | Webhook |
| sgdistributedlogs.stackgres.io | stackgres.io | SGDistributedLogs | v1 | v1 | Webhook |
| sginstanceprofiles.stackgres.io | stackgres.io | SGInstanceProfile | v1 | v1 | Webhook |
| sgobjectstorages.stackgres.io | stackgres.io | SGObjectStorage | v1beta1 | v1beta1 | Webhook |
| sgpgconfigs.stackgres.io | stackgres.io | SGPostgresConfig | v1 | v1 | Webhook |
| sgpoolconfigs.stackgres.io | stackgres.io | SGPoolingConfig | v1 | v1 | Webhook |
| sgscripts.stackgres.io | stackgres.io | SGScript | v1 | v1 | Webhook |
| sgshardedbackups.stackgres.io | stackgres.io | SGShardedBackup | v1 | v1 | Webhook |
| sgshardedclusters.stackgres.io | stackgres.io | SGShardedCluster | v1alpha1 | v1alpha1 | Webhook |
| sgshardeddbops.stackgres.io | stackgres.io | SGShardedDbOps | v1 | v1 | Webhook |
| sgstreams.stackgres.io | stackgres.io | SGStream | v1alpha1 | v1alpha1 | Webhook |
| sparkapplications.sparkoperator.k8s.io | sparkoperator.k8s.io | SparkApplication | v1beta2 | v1beta2 | None |
| sparkconnects.sparkoperator.k8s.io | sparkoperator.k8s.io | SparkConnect | v1alpha1 | v1alpha1 | None |
| strimzipodsets.core.strimzi.io | core.strimzi.io | StrimziPodSet | v1, v1beta2 | v1beta2 | None |
| thanosrulers.monitoring.coreos.com | monitoring.coreos.com | ThanosRuler | v1 | v1 | None |
| tokens.management.cattle.io | management.cattle.io | Token | v3 | v3 | None |
| triggerauthentications.keda.sh | keda.sh | TriggerAuthentication | v1alpha1 | v1alpha1 | None |
| userattributes.management.cattle.io | management.cattle.io | UserAttribute | v3 | v3 | None |
| users.management.cattle.io | management.cattle.io | User | v3 | v3 | None |

## Step 4 — Controllers / Operators Detected

| Controller | Installed (from image) | Target Compatibility | Status | Upgrade Timing |
| --- | --- | --- | --- | --- |
| ingress-nginx | `default	ingress-nginx-controller	registry.k8s.io/ingress-nginx/controller:v1.6.4@sha256:15be4666c530` | <=1.26 vs 1.31 | CRITICAL | Before Kubernetes upgrade |
| rancher-agent | `cattle-system	cattle-cluster-agent	rancher/rancher-agent:v2.8.3` | <=1.28 vs 1.31 | CRITICAL | Before Kubernetes upgrade |
| rancher-webhook | `cattle-system	rancher-webhook	rancher/rancher-webhook:v0.4.18` | <=1.28 vs 1.31 | CRITICAL | Before Kubernetes upgrade |
| fleet-agent | `cattle-fleet-system	fleet-agent	rancher/fleet-agent:v0.9.17` | <=1.28 vs 1.31 | CRITICAL | Before Kubernetes upgrade |
| cert-manager | `cert-manager	cert-manager	quay.io/jetstack/cert-manager-controller:v1.15.2` | <=1.31 vs 1.31 | GOOD | Optional |
| keda | `default	keda-operator	ghcr.io/kedacore/keda:2.13.1` | <=1.29 vs 1.31 | HIGH RISK | Before Kubernetes upgrade |
| prometheus-operator | `monitoring	prometheus-kube-prometheus-operator	quay.io/prometheus-operator/prometheus-operator:v0.85` | <=1.31 vs 1.31 | GOOD | Optional |
| strimzi | `default	strimzi-cluster-entity-operator	quay.io/strimzi/operator:0.50.0 quay.io/strimzi/operator:0.5` | <=1.31 vs 1.31 | GOOD | Optional |
| stackgres | `default	stackgres-operator	quay.io/stackgres/operator:1.15.0` | unverified vs 1.31 | HIGH RISK | Before Kubernetes upgrade |
| spark-operator | `default	spark-operator-controller	ghcr.io/kubeflow/spark-operator/controller:2.4.0` | unverified vs 1.31 | HIGH RISK | Before Kubernetes upgrade |
| aws-ebs-csi-driver | `kube-system	ebs-csi-controller	602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/aws-ebs-csi-driver:` | <=1.30 vs 1.31 | HIGH RISK | After Kubernetes upgrade |
| aws-efs-csi-driver | `kube-system	efs-csi-controller	public.ecr.aws/efs-csi-driver/amazon/aws-efs-csi-driver:v2.0.4 public` | <=1.29 vs 1.31 | HIGH RISK | Before Kubernetes upgrade |
| aws-fsx-openzfs-csi-driver | `kube-system	fsx-openzfs-csi-controller	public.ecr.aws/fsx-csi-driver/aws-fsx-openzfs-csi-driver:v1.2` | <=1.26 vs 1.31 | CRITICAL | Before Kubernetes upgrade |
| vpc-cni | `kube-system	aws-node	602401143452.dkr.ecr.ap-south-1.amazonaws.com/amazon-k8s-cni:v1.19.2-eksbuild.5` | <=1.31 vs 1.31 | GOOD | After Kubernetes upgrade |
| coredns | `kube-system	coredns	602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/coredns:v1.11.4-eksbuild.2` | <=1.31 vs 1.31 | GOOD | After Kubernetes upgrade |
| kube-proxy | `kube-system	kube-proxy	602401143452.dkr.ecr.ap-south-1.amazonaws.com/eks/kube-proxy:v1.30.9-minimal-` | <=1.30 vs 1.31 | HIGH RISK | After Kubernetes upgrade |
| metrics-server | `kube-system	metrics-server	registry.k8s.io/metrics-server/metrics-server:v0.7.1` | <=1.31 vs 1.31 | GOOD | Optional |

### Break detail — ingress-nginx

```text
WHAT WILL BREAK:
ingress-nginx unsupported on Kubernetes 1.31 (Official support matrix lists v1.6.4 for k8s 1.23–1.26 only. Upgrade to >=1.11 / 1.12+ for 1.30/1.31.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
Critical
REMEDIATION:
Before Kubernetes upgrade: upgrade ingress-nginx to a release validated for 1.31.
```

### Break detail — rancher-agent

```text
WHAT WILL BREAK:
rancher-agent unsupported on Kubernetes 1.31 (Rancher 2.8.x supports up to Kubernetes 1.28. 1.30+ needs Rancher 2.9+; 1.31 typically needs newer Rancher (2.10+ depending on matrix).)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
Critical
REMEDIATION:
Before Kubernetes upgrade: upgrade rancher-agent to a release validated for 1.31.
```

### Break detail — rancher-webhook

```text
WHAT WILL BREAK:
rancher-webhook unsupported on Kubernetes 1.31 (Tied to Rancher 2.8 line; upgrade with Rancher manager/agent before target k8s.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
Critical
REMEDIATION:
Before Kubernetes upgrade: upgrade rancher-webhook to a release validated for 1.31.
```

### Break detail — fleet-agent

```text
WHAT WILL BREAK:
fleet-agent unsupported on Kubernetes 1.31 (Fleet agent version aligned with Rancher 2.8; verify against Rancher upgrade path.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
Critical
REMEDIATION:
Before Kubernetes upgrade: upgrade fleet-agent to a release validated for 1.31.
```

### Break detail — keda

```text
WHAT WILL BREAK:
keda unsupported on Kubernetes 1.31 (KEDA 2.13 targeted older k8s lines; upgrade to a 2.15+/2.16+ release validated for 1.30/1.31 before or immediately after control-plane upgrade.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
Before Kubernetes upgrade: upgrade keda to a release validated for 1.31.
```

### Break detail — stackgres

```text
WHAT WILL BREAK:
stackgres unsupported on Kubernetes 1.31 (StackGres 1.15 installed with Fail-policy webhooks — vendor k8s compatibility must be confirmed; treat as risk until verified.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
Before Kubernetes upgrade: upgrade stackgres to a release validated for 1.31.
```

### Break detail — spark-operator

```text
WHAT WILL BREAK:
spark-operator unsupported on Kubernetes 1.31 (Spark operator 2.4 with Fail webhooks on SparkApplication — confirm Kubeflow spark-operator support for target k8s.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
Before Kubernetes upgrade: upgrade spark-operator to a release validated for 1.31.
```

### Break detail — aws-ebs-csi-driver

```text
WHAT WILL BREAK:
aws-ebs-csi-driver unsupported on Kubernetes 1.31 (EBS CSI images tagged with eks-1-30 sidecars. Upgrade EKS addon to the 1.31-compatible build during/after control-plane upgrade.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
After Kubernetes upgrade: upgrade aws-ebs-csi-driver to a release validated for 1.31.
```

### Break detail — aws-efs-csi-driver

```text
WHAT WILL BREAK:
aws-efs-csi-driver unsupported on Kubernetes 1.31 (EFS CSI v2.0.4 with eks-1-29 sidecars — bump addon before or with node/control-plane upgrade to 1.31.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
Before Kubernetes upgrade: upgrade aws-efs-csi-driver to a release validated for 1.31.
```

### Break detail — aws-fsx-openzfs-csi-driver

```text
WHAT WILL BREAK:
aws-fsx-openzfs-csi-driver unsupported on Kubernetes 1.31 (FSx OpenZFS CSI sidecars labeled eks-1-26-latest — high risk on 1.30 already; must upgrade before 1.31.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
Critical
REMEDIATION:
Before Kubernetes upgrade: upgrade aws-fsx-openzfs-csi-driver to a release validated for 1.31.
```

### Break detail — kube-proxy

```text
WHAT WILL BREAK:
kube-proxy unsupported on Kubernetes 1.31 (kube-proxy is pinned to 1.30 — must be upgraded with the EKS control plane / addon to 1.31.)
WHEN IT WILL BREAK:
Immediately After Upgrade / First Deployment / First Reconciliation
IMPACT:
Partial Outage / Deployment Failure / Reconciliation Failure
SEVERITY:
High
REMEDIATION:
After Kubernetes upgrade: upgrade kube-proxy to a release validated for 1.31.
```

## Step 5 — Kubernetes Release Notes (intermediate versions)

Review **every** minor between source and target (do not skip):

- 1.30 → 1.31: https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.31.md
  - EKS notes: https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions-standard.html

Notable themes for 1.30 → 1.31 (non-exhaustive):
- AppArmor fields graduated / structured; validate securityContext usage.
- Continued PSA enforcement expectations (PSP long removed — already gone).
- Addon skew: kube-proxy/CoreDNS/VPC CNI/EBS CSI must match EKS-recommended builds.
- No PSP-era API removals in this hop, but operator support is the dominant risk on this cluster.

## Step 6 — API Removal Analysis

No classic removed built-in APIs from the 1.30→1.31 window were found in `kubectl api-resources` / workload listings. CRD `v1beta1`/`v1alpha1` resources remain (Strimzi/Spark/StackGres/AWS) — these are extension APIs, not Kubernetes built-in removals, but still require operator support.

## Step 7 — Deprecated API Analysis

| Namespace / Scope | Object / API | Risk Level | Migration Required |
| --- | --- | --- | --- |
| metrics.k8s.io | v1beta1 NodeMetrics/PodMetrics | Low | No (metrics API still v1beta1 upstream) |
| kafka.strimzi.io | v1beta2 resources | Medium | Follow Strimzi API migration guides over time |
| sparkoperator.k8s.io | v1beta2 SparkApplication | Medium | Confirm operator upgrade path |
| stackgres.io | v1beta1 SGObjectStorage | Medium | Confirm StackGres upgrade path |
| vpcresources.k8s.aws | v1beta1 SecurityGroupPolicy | Low | AWS VPC resource controller managed |

## Step 8 — CRD Compatibility Analysis

### `alertmanagerconfigs.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `AlertmanagerConfig`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `alertmanagers.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `Alertmanager`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `apiservices.management.cattle.io`

- Group/Kind: `management.cattle.io` / `APIService`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `applicationnetworkpolicies.networking.k8s.aws`

- Group/Kind: `networking.k8s.aws` / `ApplicationNetworkPolicy`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `apps.catalog.cattle.io`

- Group/Kind: `catalog.cattle.io` / `App`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `authconfigs.management.cattle.io`

- Group/Kind: `management.cattle.io` / `AuthConfig`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `blockdeviceclaims.openebs.io`

- Group/Kind: `openebs.io` / `BlockDeviceClaim`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `blockdevices.openebs.io`

- Group/Kind: `openebs.io` / `BlockDevice`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `certificaterequests.cert-manager.io`

- Group/Kind: `cert-manager.io` / `CertificateRequest`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `certificates.cert-manager.io`

- Group/Kind: `cert-manager.io` / `Certificate`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `challenges.acme.cert-manager.io`

- Group/Kind: `acme.cert-manager.io` / `Challenge`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `cloudeventsources.eventing.keda.sh`

- Group/Kind: `eventing.keda.sh` / `CloudEventSource`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `clusterissuers.cert-manager.io`

- Group/Kind: `cert-manager.io` / `ClusterIssuer`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `clusternetworkpolicies.networking.k8s.aws`

- Group/Kind: `networking.k8s.aws` / `ClusterNetworkPolicy`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `clusterpolicyendpoints.networking.k8s.aws`

- Group/Kind: `networking.k8s.aws` / `ClusterPolicyEndpoint`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `clusterregistrationtokens.management.cattle.io`

- Group/Kind: `management.cattle.io` / `ClusterRegistrationToken`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `clusterrepos.catalog.cattle.io`

- Group/Kind: `catalog.cattle.io` / `ClusterRepo`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `clusters.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Cluster`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `clustertriggerauthentications.keda.sh`

- Group/Kind: `keda.sh` / `ClusterTriggerAuthentication`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `cninodes.vpcresources.k8s.aws`

- Group/Kind: `vpcresources.k8s.aws` / `CNINode`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `eniconfigs.crd.k8s.amazonaws.com`

- Group/Kind: `crd.k8s.amazonaws.com` / `ENIConfig`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `features.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Feature`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `groupmembers.management.cattle.io`

- Group/Kind: `management.cattle.io` / `GroupMember`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `groups.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Group`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `issuers.cert-manager.io`

- Group/Kind: `cert-manager.io` / `Issuer`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkabridges.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaBridge`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkaconnectors.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaConnector`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkaconnects.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaConnect`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkamirrormaker2s.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaMirrorMaker2`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkamirrormakers.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaMirrorMaker`
- Served: `v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkanodepools.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaNodePool`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkarebalances.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaRebalance`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkas.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `Kafka`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkatopics.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaTopic`
- Served: `v1, v1beta2, v1beta1, v1alpha1` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `kafkausers.kafka.strimzi.io`

- Group/Kind: `kafka.strimzi.io` / `KafkaUser`
- Served: `v1, v1beta2, v1beta1, v1alpha1` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `navlinks.ui.cattle.io`

- Group/Kind: `ui.cattle.io` / `NavLink`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `operations.catalog.cattle.io`

- Group/Kind: `catalog.cattle.io` / `Operation`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `orders.acme.cert-manager.io`

- Group/Kind: `acme.cert-manager.io` / `Order`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `podmonitors.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `PodMonitor`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `podsecurityadmissionconfigurationtemplates.management.cattle.io`

- Group/Kind: `management.cattle.io` / `PodSecurityAdmissionConfigurationTemplate`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `policyendpoints.networking.k8s.aws`

- Group/Kind: `networking.k8s.aws` / `PolicyEndpoint`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `preferences.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Preference`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `probes.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `Probe`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `prometheusagents.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `PrometheusAgent`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `prometheuses.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `Prometheus`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `prometheusrules.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `PrometheusRule`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `scaledjobs.keda.sh`

- Group/Kind: `keda.sh` / `ScaledJob`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `scaledobjects.keda.sh`

- Group/Kind: `keda.sh` / `ScaledObject`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `scheduledsparkapplications.sparkoperator.k8s.io`

- Group/Kind: `sparkoperator.k8s.io` / `ScheduledSparkApplication`
- Served: `v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `scrapeconfigs.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `ScrapeConfig`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `securitygrouppolicies.vpcresources.k8s.aws`

- Group/Kind: `vpcresources.k8s.aws` / `SecurityGroupPolicy`
- Served: `v1beta1` | Storage: `v1beta1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `servicemonitors.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `ServiceMonitor`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `settings.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Setting`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `sgbackups.stackgres.io`

- Group/Kind: `stackgres.io` / `SGBackup`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgclusters.stackgres.io`

- Group/Kind: `stackgres.io` / `SGCluster`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgconfigs.stackgres.io`

- Group/Kind: `stackgres.io` / `SGConfig`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgdbops.stackgres.io`

- Group/Kind: `stackgres.io` / `SGDbOps`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgdistributedlogs.stackgres.io`

- Group/Kind: `stackgres.io` / `SGDistributedLogs`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sginstanceprofiles.stackgres.io`

- Group/Kind: `stackgres.io` / `SGInstanceProfile`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgobjectstorages.stackgres.io`

- Group/Kind: `stackgres.io` / `SGObjectStorage`
- Served: `v1beta1` | Storage: `v1beta1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgpgconfigs.stackgres.io`

- Group/Kind: `stackgres.io` / `SGPostgresConfig`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgpoolconfigs.stackgres.io`

- Group/Kind: `stackgres.io` / `SGPoolingConfig`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgscripts.stackgres.io`

- Group/Kind: `stackgres.io` / `SGScript`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgshardedbackups.stackgres.io`

- Group/Kind: `stackgres.io` / `SGShardedBackup`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgshardedclusters.stackgres.io`

- Group/Kind: `stackgres.io` / `SGShardedCluster`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency; alpha storage version
```

### `sgshardeddbops.stackgres.io`

- Group/Kind: `stackgres.io` / `SGShardedDbOps`
- Served: `v1` | Storage: `v1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency
```

### `sgstreams.stackgres.io`

- Group/Kind: `stackgres.io` / `SGStream`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `Webhook` (webhook=yes)

```text
Could this CRD break after upgrade?
YES

Reason:
conversion webhook dependency; alpha storage version
```

### `sparkapplications.sparkoperator.k8s.io`

- Group/Kind: `sparkoperator.k8s.io` / `SparkApplication`
- Served: `v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `sparkconnects.sparkoperator.k8s.io`

- Group/Kind: `sparkoperator.k8s.io` / `SparkConnect`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `strimzipodsets.core.strimzi.io`

- Group/Kind: `core.strimzi.io` / `StrimziPodSet`
- Served: `v1, v1beta2` | Storage: `v1beta2`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `thanosrulers.monitoring.coreos.com`

- Group/Kind: `monitoring.coreos.com` / `ThanosRuler`
- Served: `v1` | Storage: `v1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `tokens.management.cattle.io`

- Group/Kind: `management.cattle.io` / `Token`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `triggerauthentications.keda.sh`

- Group/Kind: `keda.sh` / `TriggerAuthentication`
- Served: `v1alpha1` | Storage: `v1alpha1`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
YES

Reason:
alpha storage version
```

### `userattributes.management.cattle.io`

- Group/Kind: `management.cattle.io` / `UserAttribute`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

### `users.management.cattle.io`

- Group/Kind: `management.cattle.io` / `User`
- Served: `v3` | Storage: `v3`
- Conversion: `None` (webhook=no)

```text
Could this CRD break after upgrade?
NO*

Reason:
no conversion webhook; still depends on matching controller version after k8s upgrade
```

\* NO means the CRD object schema itself is not known-broken by the k8s minor hop; controller compatibility is assessed separately.

## Step 9 — Controller Compatibility Summary

See Step 4 table. Controllers marked CRITICAL/HIGH RISK must be remediated per timing column.

## Step 10 — Admission Webhook Analysis

```text
ValidatingWebhookConfiguration/cert-manager-webhook	webhook.cert-manager.io|Fail|None 
ValidatingWebhookConfiguration/ingress-nginx-admission	validate.nginx.ingress.kubernetes.io|Fail|None 
ValidatingWebhookConfiguration/keda-admission	vscaledobject.kb.io|Ignore|None vstriggerauthentication.kb.io|Ignore|None vsclustertriggerauthentication.kb.io|Ignore|None 
ValidatingWebhookConfiguration/prometheus-kube-prometheus-admission	prometheusrulemutate.monitoring.coreos.com|Ignore|None 
ValidatingWebhookConfiguration/rancher.cattle.io	rancher.cattle.io.features.management.cattle.io|Ignore|None rancher.cattle.io.clusters.management.cattle.io|Ignore|None rancher.cattle.io.clusters.provisioning.cattle.io|Fail|None rancher.cattle.io.rke-machine-config.cattle.io|Fail|None rancher.cattle.io.namespaces|Fail|None rancher.cattle.io.namespaces.create-non-kubesystem|Fail|None rancher.cattle.io.namespaces.create-kubesystem-only|Ignore|None 
ValidatingWebhookConfiguration/spark-operator-webhook	validate-sparkoperator-k8s-io-v1beta2-sparkapplication.sparkoperator.k8s.io|Fail|NoneOnDryRun validate-sparkoperator-k8s-io-v1beta2-scheduledsparkapplication.sparkoperator.k8s.io|Fail|NoneOnDryRun 
ValidatingWebhookConfiguration/stackgres-operator	sgcluster.validating-webhook.stackgres.io|Fail|None sginstanceprofile.validating-webhook.stackgres.io|Fail|None sgpgconfig.validating-webhook.stackgres.io|Fail|None sgpoolconfig.validating-webhook.stackgres.io|Fail|None sgbackup.validating-webhook.stackgres.io|Fail|None sgdistributedlogs.validating-webhook.stackgres.io|Fail|None sgdbops.validating-webhook.stackgres.io|Fail|None sgobjectstorage.validating-webhook.stackgres.io|Fail|None sgscript.validating-webhook.stackgres.io|Fail|None sgshardedcluster.validating-webhook.stackgres.io|Fail|None sgshardedbackup.validating-webhook.stackgres.io|Fail|None sgshardeddbops.validating-webhook.stackgres.io|Fail|None sgstream.validating-webhook.stackgres.io|Fail|None 
ValidatingWebhookConfiguration/vpc-resource-validating-webhook	vpod.vpc.k8s.aws|Ignore|None vnode.vpc.k8s.aws|Ignore|None 
MutatingWebhookConfiguration/cert-manager-webhook	webhook.cert-manager.io|Fail|None 
MutatingWebhookConfiguration/pod-identity-webhook	iam-for-pods.amazonaws.com|Ignore|None 
MutatingWebhookConfiguration/prometheus-kube-prometheus-admission	prometheusrulemutate.monitoring.coreos.com|Ignore|None 
MutatingWebhookConfiguration/rancher.cattle.io	rancher.cattle.io.clusters.provisioning.cattle.io|Fail|NoneOnDryRun rancher.cattle.io.clusters.management.cattle.io|Fail|NoneOnDryRun rancher.cattle.io.fleetworkspaces.management.cattle.io|Fail|NoneOnDryRun rancher.cattle.io.rke-machine-config.cattle.io|Fail|NoneOnDryRun 
MutatingWebhookConfiguration/spark-operator-webhook	mutate--v1-pod.sparkoperator.k8s.io|Fail|NoneOnDryRun mutate-sparkoperator-k8s-io-v1beta2-sparkapplication.sparkoperator.k8s.io|Fail|NoneOnDryRun mutate-sparkoperator-k8s-io-v1beta2-scheduledsparkapplication.sparkoperator.k8s.io|Fail|NoneOnDryRun 
MutatingWebhookConfiguration/stackgres-operator	sgcluster.mutating-webhook.stackgres.io|Fail|None sginstanceprofile.mutating-webhook.stackgres.io|Fail|None sgpgconfig.mutating-webhook.stackgres.io|Fail|None sgpoolconfig.mutating-webhook.stackgres.io|Fail|None sgbackup.mutating-webhook.stackgres.io|Fail|None sgdistributedlogs.mutating-webhook.stackgres.io|Fail|None sgdbops.mutating-webhook.stackgres.io|Fail|None sgobjectstorage.mutating-webhook.stackgres.io|Fail|None sgscript.mutating-webhook.stackgres.io|Fail|None sgshardedcluster.mutating-webhook.stackgres.io|Fail|None sgshardedbackup.mutating-webhook.stackgres.io|Fail|None sgshardeddbops.mutating-webhook.stackgres.io|Fail|None sgstream.mutating-webhook.stackgres.io|Fail|None 
MutatingWebhookConfiguration/vpc-resource-mutating-webhook	mpod.vpc.k8s.aws|Ignore|None
```

```text
Can webhook failures block workloads?
YES

Can webhook fail after upgrade?
YES

Reason:
cert-manager, ingress-nginx, rancher (namespace/cluster), spark-operator, and stackgres webhooks use failurePolicy=Fail. If those pods are not Ready after the upgrade (image pull, API skew, crash), CREATE/UPDATE of covered resources will be rejected.
```

## Step 11 — Networking Compatibility

```text
Can networking break after upgrade?
YES

Why?
ingress-nginx v1.6.4 is far outside supported k8s versions; kube-proxy is still v1.30; VPC CNI must be upgraded with EKS. NetworkPolicies exist — CNI network-policy agent must remain healthy.
```

## Step 12 — Storage Compatibility

```text
NAME                      ATTACHREQUIRED   PODINFOONMOUNT   STORAGECAPACITY   TOKENREQUESTS   REQUIRESREPUBLISH   MODES        AGE
ebs.csi.aws.com           true             false            false             <unset>         false               Persistent   446d
efs.csi.aws.com           false            false            false             <unset>         false               Persistent   446d
fsx.openzfs.csi.aws.com   false            false            false             <unset>         false               Persistent   234d
```

```text
Can storage become inaccessible?
YES

Why?
EBS/EFS/FSx CSI drivers must match the node/kubelet version. FSx sidecars are on eks-1-26 artifacts; EFS on eks-1-29. Node rolls with mismatched CSI node pods can block mount/attach. In-tree aws-ebs StorageClasses still present.
```

## Step 13 — Security Compatibility

```text
Can security changes break workloads?
YES

Why?
Rancher namespace admission webhooks (Fail) can block namespace operations. Privileged/hostNetwork/hostPath workloads exist for CNI/CSI — node OS/AMI changes during Bottlerocket bump can surface PSA or SELinux/AppArmor differences. PSP already absent (expected).
```

## Step 14 — Runtime Compatibility

```text
NAME                                         STATUS                     ROLES    AGE    VERSION                INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                                KERNEL-VERSION   CONTAINER-RUNTIME
ip-10-0-29-18.ap-south-1.compute.internal    Ready,SchedulingDisabled   <none>   165d   v1.30.10-eks-1a9dacd   10.0.29.18    <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
ip-10-0-63-213.ap-south-1.compute.internal   Ready                      <none>   165d   v1.30.10-eks-1a9dacd   10.0.63.213   <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
ip-10-0-7-113.ap-south-1.compute.internal    Ready                      <none>   154d   v1.30.10-eks-1a9dacd   10.0.7.113    <none>        Bottlerocket OS 1.38.0 (aws-k8s-1.30)   6.1.132          containerd://1.7.27+bottlerocket
```

- Runtime: containerd (Bottlerocket)
- Node kubelet: 1.30.x — must become 1.31.x via nodegroup AMI roll
- Control plane (EKS) can temporarily skew +1 minor ahead of kubelets during rolling upgrade — keep drains orderly

## Step 15 — Resource Pressure

```text
NAME                                         CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
ip-10-0-29-18.ap-south-1.compute.internal    710m         8%       14179Mi         46%         
ip-10-0-63-213.ap-south-1.compute.internal   5810m        73%      25853Mi         85%         
ip-10-0-7-113.ap-south-1.compute.internal    1026m        12%      21696Mi         70%
```

**Eviction / drain risk:** ip-10-0-63-213.ap-south-1.compute.internal memory 85%
**Capacity risk:** cordoned nodes: ip-10-0-29-18.ap-south-1.compute.internal

## Step 16 — Upgrade Simulation

### Control Plane

```text
Status:
GOOD

Reason:
Managed EKS control plane (via Rancher) — AWS owns CP upgrade, but Rancher agent skew is a management-plane risk.
```

### Nodes

```text
Status:
HIGH RISK

Reason:
1 cordoned; memory pressure hosts=1; 3-node worker pool.
```

### APIs

```text
Status:
GOOD

Reason:
No high-impact built-in API removals identified for 1.30→1.31.
```

### CRDs

```text
Status:
WARNING

Reason:
75 CRDs; conversion/alpha storage present — verify operators before upgrade.
```

### Controllers

```text
Status:
CRITICAL

Reason:
5 controller(s) outside supported k8s range.
```

### Networking

```text
Status:
CRITICAL

Reason:
ingress-nginx version unsupported for target Kubernetes.
```

### Storage

```text
Status:
HIGH RISK

Reason:
FSx/EFS CSI sidecars lag target; EBS CSI needs 1.31 addon bump.
```

### Security

```text
Status:
WARNING

Reason:
Privileged/hostNetwork/hostPath workloads typical of CNI/CSI observed; PSA/Rancher namespace webhooks use Fail.
```

## Step 17 — Failure Scenario Analysis

### Could workloads fail to start?

```text
YES

Reason:
Unsupported ingress-nginx / Fail webhooks / node drain pressure can prevent scheduling or admission.
```

### Could controllers crash?

```text
YES

Reason:
Rancher agent, KEDA, StackGres, Spark-operator may hit API/client skew on 1.31 without upgrades.
```

### Could CRDs become unreadable?

```text
NO

Reason:
No evidence of storage-version removal for this hop; unreadable CRDs unlikely unless conversion webhooks die mid-read of multi-version objects.
```

### Could CRD controllers stop reconciling?

```text
YES

Reason:
If operators are incompatible they can crash-loop and stop reconciling Kafka/Postgres/Spark/KEDA objects.
```

### Could admission webhooks block deployments?

```text
YES

Reason:
Multiple failurePolicy=Fail webhooks (ingress-nginx, cert-manager, rancher, spark, stackgres).
```

### Could storage become inaccessible?

```text
YES

Reason:
CSI addon/node skew (especially FSx/EFS) during node AMI roll can break mounts.
```

### Could networking break?

```text
YES

Reason:
ingress-nginx unsupported; kube-proxy/VPC CNI must be upgraded with EKS.
```

### Could node upgrades fail?

```text
YES

Reason:
Cordoned node + high memory node + 3-node pool increases drain/PDB deadlock risk.
```

### Could kubelets fail to register?

```text
YES

Reason:
Wrong Bottlerocket variant (aws-k8s-1.30 on 1.31 CP beyond skew) or CNI failure can block Ready.
```

### Could the control plane fail?

```text
NO

Reason:
EKS managed control plane upgrades are generally reliable; residual risk is operational (addons), not etcd DIY failure.
```

## Risk Matrix

| Area | Status | Severity | Explanation |
| --- | --- | --- | --- |
| APIs | GOOD | Low | No high-impact built-in API removals identified for 1.30→1.31. |
| CRDs | WARNING | Medium | 75 CRDs; conversion/alpha storage present — verify operators before upgrade. |
| Controllers | CRITICAL | Critical | 5 controller(s) outside supported k8s range. |
| Webhooks | HIGH RISK | High | 9 Fail-policy webhook groups can block creates/updates if backends are down. |
| Networking | CRITICAL | Critical | ingress-nginx version unsupported for target Kubernetes. |
| Storage | HIGH RISK | High | FSx/EFS CSI sidecars lag target; EBS CSI needs 1.31 addon bump. |
| Security | WARNING | Medium | Privileged/hostNetwork/hostPath workloads typical of CNI/CSI observed; PSA/Rancher namespace webhooks use Fail. |
| Runtime | WARNING | Medium | containerd on Bottlerocket aws-k8s-1.30 must be replaced with 1.31 AMI variant. |
| Nodes | HIGH RISK | High | 1 cordoned; memory pressure hosts=1; 3-node worker pool. |
| Control Plane | GOOD | Low | Managed EKS control plane (via Rancher) — AWS owns CP upgrade, but Rancher agent skew is a management-plane risk. |

## Readiness Score

```text
Readiness Score: 7/100
```

Band: **Not recommended**

## Confidence Score

```text
Confidence Score: 80%
```

Factors:
- Inventory completeness: good (0 collection warnings)
- Release notes: reviewed for 1.30→1.31 themes + EKS addon expectations
- Controller compatibility: mix of verified (ingress-nginx, Rancher) and unverified (StackGres/Spark)
- CRD verification: 75 CRDs summarized from live cluster
- Unknown components reduce confidence (custom images, vendor matrices)

---

**Mandatory conservatism note:** Compatibility was not assumed. Unverified operators were classified as risk.
