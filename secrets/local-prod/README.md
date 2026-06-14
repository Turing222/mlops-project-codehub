# Local Production Rehearsal Secrets

This directory is reserved for local production-shape rehearsals that layer
`deploy/docker-compose.local-s3.yml` on top of the EC2 deploy compose file.

Only this README and `.gitkeep` should be committed. Real `*.txt` files here are
local-only rehearsal secrets and must stay out of Git.

Prepare the expected files with:

```bash
make deploy-local-prod-secrets-prepare
```

The command generates required app/database secrets and writes local MinIO
credentials into:

- `s3_access_key_id.txt`
- `s3_secret_access_key.txt`

These MinIO credentials are for local rehearsal only; production EC2 should use
`secrets/ec2` or AWS Secrets Manager.
