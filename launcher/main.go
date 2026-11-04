// Lanzador de VoiceLab AI para Windows.
//
// Abre la aplicación (que sigue siendo Python) con el intérprete privado de
// la instalación, sin ventana de consola, como cualquier programa. Si la app
// aún no está instalada, ofrece ejecutar el instalador.
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

const appName = "VoiceLab AI"

func msgBox(text string, flags uintptr) int {
	p := syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString(appName)
	r, _, _ := p.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), flags)
	return int(r)
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// Misma identidad de barra de tareas que la ventana de la app.
func setAppID() {
	p := syscall.NewLazyDLL("shell32.dll").NewProc("SetCurrentProcessExplicitAppUserModelID")
	id, _ := syscall.UTF16PtrFromString("VoiceLabAI.Studio")
	p.Call(uintptr(unsafe.Pointer(id)))
}

func main() {
	setAppID()
	exe, err := os.Executable()
	if err != nil {
		msgBox("No se pudo localizar el lanzador.", 0x10)
		os.Exit(1)
	}
	dir := filepath.Dir(exe)
	roots := []string{dir, filepath.Join(os.Getenv("LOCALAPPDATA"), "Programs", appName)}
	for _, root := range roots {
		pyw := filepath.Join(root, "runtime", "Scripts", "pythonw.exe")
		if exists(pyw) && exists(filepath.Join(root, "voicelab", "__init__.py")) {
			cmd := exec.Command(pyw, append([]string{"-m", "voicelab"}, os.Args[1:]...)...)
			cmd.Dir = root
			cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
			if err := cmd.Start(); err != nil {
				msgBox("No se pudo abrir VoiceLab AI:\n\n"+err.Error()+"\n\nVuelve a ejecutar «Instalar VoiceLab AI.bat».", 0x10)
				os.Exit(1)
			}
			return
		}
	}
	installer := filepath.Join(dir, "Instalar VoiceLab AI.bat")
	if exists(installer) {
		if msgBox("VoiceLab AI todavía no está instalado en este equipo.\n\n¿Quieres instalarlo ahora? La primera vez tarda 1–3 minutos.", 0x4|0x40) == 6 {
			cmd := exec.Command("cmd.exe")
			cmd.Dir = dir
			cmd.SysProcAttr = &syscall.SysProcAttr{
				CmdLine:       `cmd.exe /c ""` + installer + `""`,
				CreationFlags: 0x00000010, // CREATE_NEW_CONSOLE: el instalador necesita su ventana
			}
			if err := cmd.Start(); err != nil {
				msgBox("No se pudo iniciar el instalador:\n\n"+err.Error(), 0x10)
				os.Exit(1)
			}
		}
		return
	}
	msgBox("No se encuentra la instalación de VoiceLab AI.\n\nEjecuta «Instalar VoiceLab AI.bat» desde la carpeta del ZIP.", 0x10)
	os.Exit(1)
}
