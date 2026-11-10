# Publishes every image SerialEM acquires as a JPEG for the SmartScope live view.
#
# SmartScope turns on the SerialEM property SaveNewImageToShrMem and starts this
# hidden when a session connects. It logs to SmartScopeLiveImage.log and stops
# when SerialEM closes.
# It rewrites live\heartbeat.txt every 5 s so the server can tell it is running.
# SerialEM writes bufferAimageList.txt where it was started, or to the property
# NewImageListPath; live_sources.txt lists the folders to look in besides this one.
param(
    [string]$ListDir = $PSScriptRoot,
    [string]$OutDir = (Join-Path $PSScriptRoot 'live'),
    [int]$MaxSize = 1024,
    [int]$Keep = 12,
    [switch]$NoFlip
)

$source = @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Threading;

public static class SmartScopeLive
{
    // IMOD shared memory files hold an MRC header, then the pixels from this offset.
    const int DataOffset = 2048;

    public class Frame
    {
        public Bitmap Image;
        public int SourceWidth, SourceHeight, Mode;
        public double PixelAngstrom;
        public ulong Signature;
    }

    // SerialEM shares buffer A again after exposures that do not return an image.
    static ulong Fingerprint(float[] values, int nx, int ny, int mode)
    {
        byte[] bytes = new byte[values.Length * 4];
        Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
        ulong hash = 14695981039346656037UL ^ (ulong)(uint)nx ^ ((ulong)(uint)ny << 20) ^ ((ulong)(uint)mode << 40);
        unchecked
        {
            for (int i = 0; i < bytes.Length; i++) hash = (hash ^ bytes[i]) * 1099511628211UL;
        }
        return hash;
    }

    public static Frame Render(Stream stream, int maxSize, bool flip)
    {
        byte[] header = new byte[DataOffset];
        ReadFully(stream, header, DataOffset);
        int nx = BitConverter.ToInt32(header, 0);
        int ny = BitConverter.ToInt32(header, 4);
        int mode = BitConverter.ToInt32(header, 12);
        int mx = BitConverter.ToInt32(header, 28);
        float xlen = BitConverter.ToSingle(header, 40);
        int bytesPerPixel = mode == 0 ? 1 : (mode == 1 || mode == 6) ? 2 : mode == 2 ? 4 : 0;
        if (nx <= 0 || ny <= 0 || nx > 32768 || ny > 32768 || bytesPerPixel == 0)
            throw new InvalidDataException(String.Format("Unsupported image: {0} x {1}, mode {2}", nx, ny, mode));

        // Averaging blocks rather than skipping pixels keeps low-dose images legible.
        int bin = Math.Max(1, (int)Math.Ceiling(Math.Max(nx, ny) / (double)maxSize));
        int width = nx / bin, height = ny / bin;
        float[] sums = new float[width * height];
        byte[] row = new byte[nx * bytesPerPixel];
        short[] shorts = new short[nx];
        ushort[] ushorts = new ushort[nx];
        float[] floats = new float[nx];
        for (int y = 0; y < height * bin; y++)
        {
            ReadFully(stream, row, row.Length);
            int offset = (y / bin) * width;
            if (mode == 1) Buffer.BlockCopy(row, 0, shorts, 0, row.Length);
            else if (mode == 6) Buffer.BlockCopy(row, 0, ushorts, 0, row.Length);
            else if (mode == 2) Buffer.BlockCopy(row, 0, floats, 0, row.Length);
            int x = 0;
            for (int ox = 0; ox < width; ox++)
            {
                float sum = 0;
                for (int k = 0; k < bin; k++, x++)
                    sum += mode == 1 ? shorts[x] : mode == 6 ? ushorts[x] : mode == 2 ? floats[x] : row[x];
                sums[offset + ox] += sum;
            }
        }

        float low, high;
        ContrastLimits(sums, out low, out high);
        float scale = high > low ? 255f / (high - low) : 0f;
        Bitmap bitmap = new Bitmap(width, height, PixelFormat.Format24bppRgb);
        BitmapData data = bitmap.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
        byte[] line = new byte[data.Stride];
        for (int y = 0; y < height; y++)
        {
            // MRC stores the bottom line first.
            int offset = (flip ? height - 1 - y : y) * width;
            for (int x = 0; x < width; x++)
            {
                float value = (sums[offset + x] - low) * scale;
                byte gray = value <= 0 ? (byte)0 : value >= 255 ? (byte)255 : (byte)value;
                line[3 * x] = gray; line[3 * x + 1] = gray; line[3 * x + 2] = gray;
            }
            Marshal.Copy(line, 0, IntPtr.Add(data.Scan0, y * data.Stride), data.Stride);
        }
        bitmap.UnlockBits(data);

        Frame frame = new Frame();
        frame.Image = bitmap;
        frame.SourceWidth = nx; frame.SourceHeight = ny; frame.Mode = mode;
        frame.PixelAngstrom = mx > 0 && xlen > 0 ? xlen / mx : 0;
        frame.Signature = Fingerprint(sums, nx, ny, mode);
        return frame;
    }

    static void ReadFully(Stream stream, byte[] buffer, int count)
    {
        int done = 0;
        while (done < count)
        {
            int read = stream.Read(buffer, done, count - done);
            if (read <= 0) throw new EndOfStreamException("Image data ended early");
            done += read;
        }
    }

    // Clips the darkest and brightest 0.5% so hot pixels and grid bars do not flatten the image.
    static void ContrastLimits(float[] values, out float low, out float high)
    {
        float min = Single.MaxValue, max = Single.MinValue;
        for (int i = 0; i < values.Length; i++)
        {
            if (values[i] < min) min = values[i];
            if (values[i] > max) max = values[i];
        }
        low = min; high = max;
        if (!(max > min)) return;
        const int Bins = 4096;
        int[] histogram = new int[Bins];
        float toBin = (Bins - 1) / (max - min);
        for (int i = 0; i < values.Length; i++) histogram[(int)((values[i] - min) * toBin)]++;
        int clip = values.Length / 200, count = 0, bin = 0;
        while (bin < Bins - 1 && count + histogram[bin] <= clip) count += histogram[bin++];
        low = min + bin / toBin;
        count = 0; bin = Bins - 1;
        while (bin > 0 && count + histogram[bin] <= clip) count += histogram[bin--];
        high = min + (bin + 1) / toBin;
    }

    public static void SaveJpeg(Bitmap bitmap, string path, long quality)
    {
        ImageCodecInfo codec = null;
        foreach (ImageCodecInfo candidate in ImageCodecInfo.GetImageEncoders())
            if (candidate.FormatID == ImageFormat.Jpeg.Guid) codec = candidate;
        EncoderParameters parameters = new EncoderParameters(1);
        parameters.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, quality);
        bitmap.Save(path, codec, parameters);
    }

    static MemoryMappedFile OpenSharedMemory(string name)
    {
        string bare = name.TrimStart('/');
        foreach (string candidate in new string[] { name, bare, "Local\\" + bare, "Global\\" + bare })
        {
            try { return MemoryMappedFile.OpenExisting(candidate, MemoryMappedFileRights.Read); }
            catch (FileNotFoundException) { }
            catch (ArgumentException) { }
            catch (UnauthorizedAccessException) { }
        }
        return null;
    }

    static string ReadShared(string path)
    {
        using (FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        using (StreamReader reader = new StreamReader(file))
            return reader.ReadToEnd();
    }

    static void ReplaceFile(string temporary, string target)
    {
        if (File.Exists(target)) File.Replace(temporary, target, null);
        else File.Move(temporary, target);
    }

    // Kept in a field: a collected mutex would let a second watcher start.
    static Mutex single;
    const string ListName = "bufferAimageList.txt";
    static string logFile;
    static int logWritten;
    const int MaxLogLines = 2000;

    static void Log(string message)
    {
        if (logWritten >= MaxLogLines) return;
        if (++logWritten == MaxLogLines) message = "Log is full, restart the watcher to see more";
        try { File.AppendAllText(logFile, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + message + "\r\n"); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    static bool SerialEMRunning()
    {
        bool found = false;
        foreach (Process process in Process.GetProcesses())
        {
            try { found |= process.ProcessName.StartsWith("SerialEM", StringComparison.OrdinalIgnoreCase); }
            catch (InvalidOperationException) { }
            process.Dispose();
        }
        return found;
    }

    static List<string> ListFiles(string listDir)
    {
        List<string> files = new List<string>();
        files.Add(Path.Combine(listDir, ListName));
        try
        {
            string sources = Path.Combine(listDir, "live_sources.txt");
            if (File.Exists(sources))
                foreach (string line in ReadShared(sources).Split(new char[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                    if (line.Trim().Length > 0 && !files.Contains(Path.Combine(line.Trim(), ListName)))
                        files.Add(Path.Combine(line.Trim(), ListName));
        }
        catch (IOException) { }
        catch (ArgumentException) { }
        return files;
    }

    // SerialEM only writes to one of the candidates; an old copy may linger in another.
    static string NewestListFile(List<string> files)
    {
        string newest = null;
        DateTime latest = DateTime.MinValue;
        foreach (string file in files)
        {
            try
            {
                if (!File.Exists(file)) continue;
                DateTime written = File.GetLastWriteTimeUtc(file);
                if (written > latest) { latest = written; newest = file; }
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
        return newest;
    }

    public static void Run(string listDir, string outDir, int maxSize, int keep, bool flip)
    {
        bool first;
        single = new Mutex(true, "SmartScopeLiveImage", out first);
        // A watcher this launch replaced may still be shutting down.
        if (!first)
            try { first = single.WaitOne(3000); }
            catch (AbandonedMutexException) { first = true; }
        if (!first) return;
        logFile = Path.Combine(listDir, "SmartScopeLiveImage.log");
        try { File.Delete(logFile); } catch (IOException) { }
        bool serialEMSeen = false;
        int idle = 0;
        List<string> listFiles = ListFiles(listDir);
        string indexFile = Path.Combine(outDir, "index.txt");
        string heartbeat = Path.Combine(outDir, "heartbeat.txt");
        Directory.CreateDirectory(outDir);
        foreach (string old in Directory.GetFiles(outDir, "frame_*.jpg")) File.Delete(old);
        if (File.Exists(indexFile)) File.Delete(indexFile);
        List<string> index = new List<string>();
        // Starting from the clock keeps frame names unique across restarts, so browsers never show a stale cached frame.
        long sequence = (long)(DateTime.UtcNow - new DateTime(2020, 1, 1)).TotalSeconds;
        string lastSeen = null, lastProblem = null;
        ulong lastSignature = 0;
        Log("Watching " + String.Join("; ", listFiles.ToArray()));
        Log("Writing frames to " + outDir);
        while (true)
        {
            Thread.Sleep(100);
            if (++idle >= 50)
            {
                idle = 0;
                try { File.WriteAllText(heartbeat, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
                // A later session may add folders while this is already running.
                List<string> current = ListFiles(listDir);
                if (String.Join(";", current.ToArray()) != String.Join(";", listFiles.ToArray()))
                {
                    listFiles = current;
                    Log("Watching " + String.Join("; ", listFiles.ToArray()));
                }
                if (SerialEMRunning()) serialEMSeen = true;
                else if (serialEMSeen)
                {
                    Log("SerialEM closed, stopping");
                    return;
                }
            }
            try
            {
                string listFile = NewestListFile(listFiles);
                if (listFile == null)
                {
                    if (lastProblem != "nolist") Log("Waiting for SerialEM to write " + ListName);
                    lastProblem = "nolist";
                    continue;
                }
                string stamp = File.GetLastWriteTimeUtc(listFile).Ticks.ToString();
                string[] names = ReadShared(listFile).Split(new char[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                if (names.Length == 0) continue;
                string name = names[names.Length - 1].Trim();
                if (listFile + stamp + name == lastSeen) continue;
                lastSeen = listFile + stamp + name;

                Frame frame;
                using (MemoryMappedFile memory = OpenSharedMemory(name))
                {
                    if (memory == null)
                    {
                        // Normal when a newer image has already replaced this one.
                        if (lastProblem != name) Log("Shared memory not found: " + name);
                        lastProblem = name;
                        continue;
                    }
                    using (Stream stream = memory.CreateViewStream(0, 0, MemoryMappedFileAccess.Read))
                        frame = Render(stream, maxSize, flip);
                }
                if (frame.Signature == lastSignature)
                {
                    frame.Image.Dispose();
                    continue;
                }
                lastSignature = frame.Signature;

                sequence++;
                string fileName = "frame_" + sequence + ".jpg";
                string target = Path.Combine(outDir, fileName);
                SaveJpeg(frame.Image, target + ".tmp", 85);
                ReplaceFile(target + ".tmp", target);
                index.Add(String.Format(CultureInfo.InvariantCulture, "{0} {1} {2} {3} {4} {5} {6:0.####}",
                    sequence, fileName, frame.Image.Width, frame.Image.Height, frame.SourceWidth, frame.SourceHeight, frame.PixelAngstrom));
                frame.Image.Dispose();
                List<string> expired = new List<string>();
                while (index.Count > keep)
                {
                    expired.Add(Path.Combine(outDir, index[0].Split(' ')[1]));
                    index.RemoveAt(0);
                }
                File.WriteAllLines(indexFile + ".tmp", index.ToArray());
                ReplaceFile(indexFile + ".tmp", indexFile);
                foreach (string old in expired)
                    try { File.Delete(old); } catch (IOException) { }
                lastProblem = null;
            }
            catch (Exception error)
            {
                if (lastProblem != error.Message) Log("Skipped an image: " + error.Message);
                lastProblem = error.Message;
            }
        }
    }
}
'@

# A new launch replaces a running watcher, so an updated script takes effect without closing SerialEM.
try {
    Get-WmiObject Win32_Process -Filter "Name = 'powershell.exe'" |
        Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*SmartScopeLiveImage.ps1*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch { }

Add-Type -TypeDefinition $source -ReferencedAssemblies System, System.Core, System.Drawing
$flip = -not $NoFlip
[SmartScopeLive]::Run($ListDir, $OutDir, $MaxSize, $Keep, $flip)
