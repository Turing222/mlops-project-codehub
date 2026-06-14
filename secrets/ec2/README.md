# EC2 Deploy Secrets

This directory is reserved for single-EC2 deployment secret files.

Only this README and `.gitkeep` should be committed. Real `*.txt` files in this
directory are local deployment secrets and must stay out of Git.

Prepare the expected files with:

```bash
make deploy-ec2-secrets-prepare
```

Required files are generated if missing:

- `secret_key.txt`
- `postgres_password.txt`
- `redis_password.txt`

Optional integration files are created empty. Fill only the files needed by the
providers enabled in `deploy/.env.ec2`.
