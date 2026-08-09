import type { FullConfig } from '@playwright/test'
import { execFileSync, execSync, spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import https from 'node:https'
import path from 'node:path'

const healthUrl = 'https://127.0.0.1:4173/api/health'

export default async function globalSetup(_config: FullConfig) {
  execSync('npm --prefix frontend run build', { stdio: 'inherit' })

  const python = process.env.MUSEECHO_E2E_PYTHON || 'python'
  const pythonPath = [path.resolve('src'), process.env.MUSEECHO_E2E_SITE_PACKAGES]
    .filter(Boolean)
    .join(path.delimiter)
  const shutdownFile = path.resolve(
    'tmp/e2e-runtime',
    `shutdown-${process.pid}-${Date.now()}.signal`,
  )
  fs.mkdirSync(path.dirname(shutdownFile), { recursive: true })
  const server = spawn(python, ['e2e/server.py', '--port', '4173'], {
    env: {
      ...process.env,
      MUSEECHO_E2E_SHUTDOWN_FILE: shutdownFile,
      PYTHONPATH: pythonPath,
    },
    stdio: 'inherit',
    windowsHide: true,
  })

  try {
    await waitForHealth(server)
  } catch (error) {
    await stopProcess(server, shutdownFile)
    throw error
  }

  return async () => stopProcess(server, shutdownFile)
}

async function waitForHealth(server: ChildProcess): Promise<void> {
  const deadline = Date.now() + 120_000
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`E2E server exited with code ${server.exitCode}`)
    }
    if (await healthIsReady()) return
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error('E2E server health check timed out')
}

function healthIsReady(): Promise<boolean> {
  return new Promise((resolve) => {
    const request = https.get(
      healthUrl,
      { rejectUnauthorized: false },
      (response) => {
        response.resume()
        resolve(response.statusCode === 200)
      },
    )
    request.setTimeout(1_000, () => request.destroy())
    request.on('error', () => resolve(false))
  })
}

async function stopProcess(server: ChildProcess, shutdownFile: string): Promise<void> {
  if (server.exitCode !== null || server.pid === undefined) return
  const exitPromise = new Promise<boolean>((resolve) => {
    if (server.exitCode !== null) resolve(true)
    else server.once('exit', () => resolve(true))
  })
  fs.writeFileSync(shutdownFile, '')
  const exited = await Promise.race([
    exitPromise,
    new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 10_000)),
  ])
  if (!exited && process.platform === 'win32') {
    try {
      execFileSync('taskkill.exe', ['/pid', String(server.pid), '/T', '/F'], {
        stdio: 'ignore',
      })
    } catch (error) {
      if (server.exitCode === null) throw error
    }
  } else if (!exited) {
    server.kill('SIGKILL')
  }
  fs.rmSync(shutdownFile, { force: true })
}
