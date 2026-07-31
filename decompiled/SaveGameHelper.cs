#define DEBUG_LOGS
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using K4os.Compression.LZ4;
using PlayFab;
using UnityEngine;
using UnityEngine.InputSystem;

public static class SaveGameHelper
{
	private class SaveDataObjects
	{
		public UserData User;

		public GameSaveDirector.GameSaveData RunSummary;

		public GameRunData RunData;
	}

	public struct GameRunFileInfo
	{
		public string GameRunId;

		public bool IsMainSave;

		public string FileName;
	}

	private static readonly string encryptString = "21398xa2";

	private static readonly byte[] encryptUnicodeBytes = Encoding.Unicode.GetBytes(encryptString);

	private static string BASELINE_VERSION = "1.0.0";

	private const string SUMMARY_DELIMITER_START = "//**";

	private static readonly byte[] SummaryDelimiterStartBytes = Encoding.UTF8.GetBytes("//**");

	private const string SUMMARY_DELIMITER_END = "**//";

	private static readonly byte[] SummaryDelimiterEndBytes = Encoding.UTF8.GetBytes("**//\n");

	public static string UserDirectoryPath;

	public const string ENCRYPTED_FILE_FORMAT = ".ftk2";

	public const string COMPRESSED_FILE_FORMAT = ".ftk2z";

	public const string UNENCRYPTED_FILE_FORMAT = ".json";

	public const int MAX_SAVE_NAME_LIMIT = 40;

	private const int RUN_DATA_BUFFER_INIT_SIZE = 8388608;

	private const int USER_DATA_BUFFER_INIT_SIZE = 65536;

	private static List<string> _retrofitBaseMapAdventures = new List<string> { "STORY_1_1", "STORY_1_2", "STORY_1_3", "STORY_1_4", "STORY_1_5" };

	private static List<string> _retrofitBaseAdventures = new List<string> { "STORY_1_1", "STORY_1_2", "STORY_1_3", "STORY_1_4", "STORY_1_5", "SIDE_ADVENTURE_DARK_CARNIVAL" };

	private static Dictionary<string, int> LORE_STORE_REFUND = new Dictionary<string, int>
	{
		{ "BOOMERANG_MILITIA_HEAVY", 6 },
		{ "POLEARM_CROOK_MEDIUM", 6 },
		{ "WHIP_MILITIA_BASIC", 6 },
		{ "BLADE_FIRE_HEAVY", 10 },
		{ "BLUNT_ICE_HEAVY", 10 }
	};

	private static List<(string oldID, string newID)> MIGRATE_USER_STATS_NEW_ID = new List<(string, string)>
	{
		("DUNGEON_LOOPS_CURRENT~SIDE_ADVENTURE_DARK_CARNIVAL", "CHALLENGE_PB~SIDE_ADVENTURE_DARK_CARNIVAL_DUNGEON_LOOPS"),
		("DUNGEON_LOOPS~SIDE_ADVENTURE_DARK_CARNIVAL_HIGH", "CHALLENGE_PB~SIDE_ADVENTURE_DARK_CARNIVAL_DUNGEON_LOOPS")
	};

	public static List<(string, string)> WEAPON_CONFIG_NAME_CHANGES = new List<(string, string)>
	{
		("GUN_MILITIA_LIGHT_00", "GUN_MILITIA_TINY_00"),
		("GUN_MILITIA_LIGHT_01", "GUN_MILITIA_TINY_01"),
		("GUN_MILITIA_LIGHT_02", "GUN_MILITIA_TINY_02"),
		("GUN_MILITIA_LIGHT_03", "GUN_MILITIA_TINY_03"),
		("GUN_GOLDEN_LIGHT_00", "GUN_GOLDEN_TINY_00")
	};

	private static MemoryStream _cachedMemoryStream = new MemoryStream(8388608);

	private static MemoryStream _cachedMemoryStream2 = new MemoryStream(8388608);

	public const char MANUAL_SAVE_ID_DELIMITER = '-';

	public static bool CompareBaselineVersion(string pGameRunVersion)
	{
		return CompareVersion(pGameRunVersion, BASELINE_VERSION) >= 0;
	}

	public static async Task<GameSaveDirector.GameSaveData> ConvertManualSaveToAutoSave(GameSaveDirector.GameSaveData pGameSaveData)
	{
		if (string.IsNullOrEmpty(pGameSaveData.manualId))
		{
			Debug.LogError("[SaveGameHelper.ConvertManualSaveToAutoSave] " + pGameSaveData.GetFileName() + " is not a manual save");
			return null;
		}
		string manualSavePath = AssetLoader.TryGetExistingGameRunFilePath(pGameSaveData.GetFileName());
		if (string.IsNullOrEmpty(manualSavePath))
		{
			Debug.LogError("[SaveGameHelper.ConvertManualSaveToAutoSave] could not find path for filename " + pGameSaveData.GetFileName());
			return null;
		}
		GameRunData gamerunData = await ReadRunDataAsync(manualSavePath);
		GameSaveDirector.GameSaveData autoSaveData = CreateGameSaveData(pGameSaveData.runID, gamerunData);
		string autoSavePath = AssetLoader.GetGameRunFilePath(autoSaveData.GetFileName());
		if (string.IsNullOrEmpty(autoSavePath))
		{
			Debug.LogError("[SaveGameHelper.ConvertManualSaveToAutoSave] failed to get path for filename " + autoSaveData.GetFileName());
			return null;
		}
		await FileIO.Delete(manualSavePath);
		await WriteRunDataAsync(autoSavePath, autoSaveData, gamerunData);
		return autoSaveData;
	}

	public static int CompareVersion(string pVersionA, string pVersionB)
	{
		Version version = _getSanitizedVersion(pVersionA);
		Version value = _getSanitizedVersion(pVersionB);
		return version.CompareTo(value);
	}

	private static Version _getSanitizedVersion(string pVersion)
	{
		string text = Regex.Replace(pVersion, "[^0-9.]", "");
		Version result = new Version("999.999.999");
		try
		{
			result = Version.Parse(text);
		}
		catch (ArgumentNullException)
		{
			Debug.LogError("Error: String to be parsed is null.");
		}
		catch (ArgumentOutOfRangeException)
		{
			Debug.LogError("Error: Negative value in '" + text + "'.");
		}
		catch (ArgumentException)
		{
			Debug.LogError("Error: Bad number of components in '" + text + "'.");
		}
		catch (FormatException)
		{
			Debug.LogError("Error: Non-integer value in '" + text + "'.");
		}
		catch (OverflowException)
		{
			Debug.LogError("Error: Number out of range in '" + text + "'.");
		}
		return result;
	}

	public static List<GameRunFileInfo> ListGameRunsSync()
	{
		return Task.Run(async () => await ListGameRuns().ConfigureAwait(continueOnCapturedContext: false)).Result;
	}

	public static async Task<List<GameRunFileInfo>> ListGameRuns()
	{
		string runsPath = AssetLoader.GameRunsDirectoryPath();
		List<GameRunFileInfo> result = new List<GameRunFileInfo>();
		return await Task.Run(delegate
		{
			DirectoryInfo directoryInfo = new DirectoryInfo(runsPath);
			if (directoryInfo.Attributes.HasFlag(FileAttributes.Directory))
			{
				FileSystemInfo[] fileSystemInfos = directoryInfo.GetFileSystemInfos();
				foreach (FileSystemInfo fileSystemInfo in fileSystemInfos)
				{
					if (Utils.JsonFileRegex.IsMatch(fileSystemInfo.Name) || Utils.Ftk2FileRegex.IsMatch(fileSystemInfo.Name))
					{
						string name = fileSystemInfo.Name;
						string text = null;
						bool isMainSave = true;
						if (name.Count((char c) => c == '-') == 5)
						{
							text = name.Substring(0, 36);
							isMainSave = false;
						}
						else
						{
							text = Path.GetFileNameWithoutExtension(name);
						}
						GameRunFileInfo item = new GameRunFileInfo
						{
							GameRunId = text,
							IsMainSave = isMainSave,
							FileName = Path.GetFileNameWithoutExtension(name)
						};
						result.Add(item);
					}
				}
			}
			return result;
		});
	}

	public static async Task<List<GameRunFileInfo>> ListPS4TransferRuns()
	{
		if (Application.platform == RuntimePlatform.PS5)
		{
			List<GameRunFileInfo> info = new List<GameRunFileInfo>();
			info.AddRange(await _getPS4TransferRunInfo(AssetLoader.GameRunFolderPrefix));
			if (AssetLoader.ManualGameRunFolderPrefix != AssetLoader.GameRunFolderPrefix)
			{
				info.AddRange(await _getPS4TransferRunInfo(AssetLoader.ManualGameRunFolderPrefix));
			}
			return info;
		}
		return new List<GameRunFileInfo>();
	}

	private static async Task<List<GameRunFileInfo>> _getPS4TransferRunInfo(string pFolderPrefix)
	{
		List<string> obj = await FileIO.ListDirectories("PS4_BACKWARDS_COMPAT:" + pFolderPrefix, sortByTime: true, descending: true);
		int prefixLength = "PS4_BACKWARDS_COMPAT:".Length + pFolderPrefix.Length;
		List<GameRunFileInfo> list = obj.ConvertAll((string f) => AssetLoader.GameRunFileInfoFromBase32(f.Substring(prefixLength)));
		List<GameRunFileInfo> list2 = new List<GameRunFileInfo>();
		foreach (GameRunFileInfo item in list)
		{
			list2.Add(new GameRunFileInfo
			{
				FileName = "ps4-" + item.FileName,
				GameRunId = "ps4-" + item.GameRunId,
				IsMainSave = item.IsMainSave
			});
		}
		return list2;
	}

	private static char _encryptOrDecryptChar(char pChar, int pIndex)
	{
		return (char)(pChar ^ encryptString[pIndex % encryptString.Length]);
	}

	private static byte _encryptOrDecryptByte(byte pByte, int pIndex)
	{
		return (byte)(pByte ^ encryptUnicodeBytes[pIndex % encryptUnicodeBytes.Length]);
	}

	private static string _encryptOrDecrypt(string pData)
	{
		StringBuilder stringBuilder = new StringBuilder(pData.Length);
		for (int i = 0; i < pData.Length; i++)
		{
			stringBuilder.Append(_encryptOrDecryptChar(pData[i], i));
		}
		return stringBuilder.ToString();
	}

	private static void _encryptOrDecrypt(byte[] pUnicodeBytes)
	{
		for (int i = 0; i < pUnicodeBytes.Length; i++)
		{
			pUnicodeBytes[i] = _encryptOrDecryptByte(pUnicodeBytes[i], i);
		}
	}

	public static byte[] LZ4Compress(string pData)
	{
		byte[] array = null;
		int num = 0;
		ushort num2 = 0;
		if (pData.StartsWith("//**"))
		{
			int length = "//**".Length;
			int num3 = pData.IndexOf("**//\n") - "//**".Length;
			num = num3 + "//**".Length + "**//\n".Length;
			array = Encoding.UTF8.GetBytes(pData, length, num3);
			num2 = (ushort)array.Length;
		}
		byte[] bytes = Encoding.UTF8.GetBytes(pData, num, pData.Length - num);
		byte[] array2 = new byte[LZ4Codec.MaximumOutputSize(bytes.Length)];
		int num4 = LZ4Codec.Encode(bytes, 0, bytes.Length, array2, 0, array2.Length);
		byte[] array3 = new byte[num4 + 4 + num2 + 2];
		array3[0] = (byte)(num2 >> 8);
		array3[1] = (byte)num2;
		if (array != null)
		{
			Array.Copy(array, 0, array3, 2, num2);
		}
		int num5 = num2 + 2;
		int num6 = bytes.Length;
		array3[num5] = (byte)(num6 >> 24);
		array3[num5 + 1] = (byte)(num6 >> 16);
		array3[num5 + 2] = (byte)(num6 >> 8);
		array3[num5 + 3] = (byte)num6;
		Array.Copy(array2, 0, array3, num5 + 4, num4);
		return array3;
	}

	public static string LZ4Decompress(byte[] pData)
	{
		int num = (pData[0] << 8) | pData[1];
		int num2 = num + 2;
		byte[] array = new byte[((pData[num2] << 24) | (pData[num2 + 1] << 16) | (pData[num2 + 2] << 8) | pData[num2 + 3]) + 128];
		int count = LZ4Codec.Decode(pData, num2 + 4, pData.Length - 4 - num2, array, 0, array.Length);
		string text = Encoding.UTF8.GetString(array, 0, count);
		StringBuilder stringBuilder = new StringBuilder((num > 0) ? (num + "//**".Length + "**//".Length + 1 + text.Length) : text.Length);
		if (num > 0)
		{
			stringBuilder.Append("//**").Append(Encoding.UTF8.GetString(pData, 2, num)).Append("**//")
				.Append("\n");
		}
		stringBuilder.Append(text);
		return stringBuilder.ToString();
	}

	public static Task WriteContentsAsync(string pFilePath, string pContents)
	{
		return Task.Run(async delegate
		{
			await _writeContentsAsync(pFilePath, pContents).ConfigureAwait(continueOnCapturedContext: false);
		});
	}

	private static async Task _writeContentsAsync(string pFilePath, string pContents)
	{
		if (string.IsNullOrEmpty(pFilePath))
		{
			Debug.LogError("File path is empty");
			return;
		}
		string extension = Path.GetExtension(pFilePath);
		string text;
		switch (extension)
		{
		case ".ftk2":
			text = _encryptOrDecrypt(pContents);
			break;
		case ".ftk2z":
		case ".json":
			text = pContents;
			break;
		default:
			throw new Exception("File format " + extension + " not supported");
		}
		if (extension == ".ftk2z")
		{
			byte[] bytes = LZ4Compress(text);
			await FileIO.WriteAllBytes(pFilePath, bytes);
		}
		else
		{
			await FileIO.WriteAllText(pFilePath, text);
		}
	}

	private static async Task _writeEncryptedContents(MemoryStream pSourceStream, MemoryStream pTargetStream)
	{
		using StreamReader sourceStream = new StreamReader(pSourceStream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true, 1024, leaveOpen: true);
		using StreamWriter targetStream = new StreamWriter(pTargetStream, Encoding.UTF8, 1024, leaveOpen: true);
		pSourceStream.Position = 0L;
		pTargetStream.Position = 0L;
		int num = 0;
		while (!sourceStream.EndOfStream)
		{
			int num2 = sourceStream.Read();
			if (num2 < 0)
			{
				throw new Exception("[SaveDataHelper._getEncryptedBytes] unexpected end of stream");
			}
			char pChar = (char)num2;
			pChar = _encryptOrDecryptChar(pChar, num);
			targetStream.Write(pChar);
			num++;
		}
		await targetStream.FlushAsync();
	}

	public static Task WriteUserDataAsync(string pFilePath, UserData pUser)
	{
		return Task.Run(async delegate
		{
			await _writeUserDataAsync(pFilePath, pUser).ConfigureAwait(continueOnCapturedContext: false);
		});
	}

	private static async Task _writeUserDataAsync(string pFilePath, UserData pUser)
	{
		if (pUser == null)
		{
			return;
		}
		if (string.IsNullOrEmpty(pFilePath))
		{
			Debug.LogError("File path is empty");
			return;
		}
		bool shouldEncrypt = pFilePath.EndsWith(".ftk2");
		if (!shouldEncrypt && !pFilePath.EndsWith(".json"))
		{
			throw new Exception("File format " + Path.GetExtension(pFilePath) + " not supported");
		}
		if (_cachedMemoryStream == null)
		{
			_cachedMemoryStream = new MemoryStream(8388608);
		}
		MemoryStreamHelper.Reset(_cachedMemoryStream);
		MemoryStream writeStream = _cachedMemoryStream;
		await JsonHelper.SerializeAsync(writeStream, pUser, pIndented: true);
		if (shouldEncrypt)
		{
			if (_cachedMemoryStream2 == null)
			{
				_cachedMemoryStream2 = new MemoryStream(8388608);
			}
			MemoryStreamHelper.Reset(_cachedMemoryStream2);
			writeStream.Position = 0L;
			await _writeEncryptedContents(writeStream, _cachedMemoryStream2);
			writeStream = _cachedMemoryStream2;
		}
		writeStream.Position = 0L;
		await FileIO.WriteStream(pFilePath, writeStream);
	}

	public static Task WriteRunDataAsync(string pFilePath, GameSaveDirector.GameSaveData pRunSummary, GameRunData pRunData)
	{
		return Task.Run(async delegate
		{
			await _writeRunDataAsync(pFilePath, pRunSummary, pRunData).ConfigureAwait(continueOnCapturedContext: false);
		});
	}

	private static async Task _writeRunDataAsync(string pFilePath, GameSaveDirector.GameSaveData pRunSummary, GameRunData pRunData)
	{
		if (string.IsNullOrEmpty(pFilePath))
		{
			Debug.LogError("File path is empty");
			return;
		}
		bool flag = pFilePath.EndsWith(".ftk2z");
		bool shouldEncrypt = !flag && pFilePath.EndsWith(".ftk2");
		if (!flag && !shouldEncrypt && !pFilePath.EndsWith(".json"))
		{
			throw new Exception("File format " + Path.GetExtension(pFilePath) + " not supported");
		}
		if (_cachedMemoryStream == null)
		{
			_cachedMemoryStream = new MemoryStream(8388608);
		}
		MemoryStreamHelper.Reset(_cachedMemoryStream);
		MemoryStream writeStream = _cachedMemoryStream;
		if (flag)
		{
			await _writeRunSummaryToCompressedStream(writeStream, pRunSummary);
			await _writeCompressedRunDataToStream(writeStream, pRunData);
		}
		else
		{
			writeStream.Write(SummaryDelimiterStartBytes);
			await JsonHelper.SerializeAsync(writeStream, pRunSummary);
			writeStream.Write(SummaryDelimiterEndBytes);
			await JsonHelper.SerializeAsync(writeStream, pRunData, pIndented: true);
			if (shouldEncrypt)
			{
				if (_cachedMemoryStream2 == null)
				{
					_cachedMemoryStream2 = new MemoryStream(8388608);
				}
				MemoryStreamHelper.Reset(_cachedMemoryStream2);
				await _writeEncryptedContents(writeStream, _cachedMemoryStream2);
				writeStream = _cachedMemoryStream2;
			}
		}
		writeStream.Position = 0L;
		await FileIO.WriteStream(pFilePath, writeStream);
	}

	public static async Task<byte[]> GetCompressedBytesForRun(GameRunData pRunData)
	{
		byte[] array = null;
		using (MemoryStream stream = new MemoryStream(8388608))
		{
			await _writeCompressedRunDataToStream(stream, pRunData);
			array = new byte[stream.Length];
			Array.Copy(stream.GetBuffer(), array, stream.Length);
		}
		return array;
	}

	private static async Task _writeRunSummaryToCompressedStream(MemoryStream pStream, GameSaveDirector.GameSaveData pRunSummary)
	{
		long startPos = pStream.Position;
		pStream.WriteByte(0);
		pStream.WriteByte(0);
		await JsonHelper.SerializeAsync(pStream, pRunSummary);
		short num = (short)(pStream.Position - 2 - startPos);
		byte[] buffer = pStream.GetBuffer();
		buffer[startPos] = (byte)(num >> 8);
		buffer[startPos + 1] = (byte)num;
	}

	private static async Task _writeCompressedRunDataToStream(MemoryStream pSourceStream, GameRunData pRunData)
	{
		long startRunPos = pSourceStream.Position;
		pSourceStream.WriteByte(0);
		pSourceStream.WriteByte(0);
		pSourceStream.WriteByte(0);
		pSourceStream.WriteByte(0);
		await JsonHelper.SerializeAsync(pSourceStream, pRunData);
		int num = (int)(pSourceStream.Position - 4 - startRunPos);
		byte[] buffer = pSourceStream.GetBuffer();
		int num2 = LZ4Codec.MaximumOutputSize(num);
		MemoryStreamHelper.Reset(_cachedMemoryStream2);
		if (num2 > _cachedMemoryStream2.Capacity)
		{
			_cachedMemoryStream2.Capacity = num2;
		}
		int count = LZ4Codec.Encode(buffer, (int)startRunPos + 4, num, _cachedMemoryStream2.GetBuffer(), 0, num2);
		buffer[startRunPos] = (byte)(num >> 24);
		buffer[startRunPos + 1] = (byte)(num >> 16);
		buffer[startRunPos + 2] = (byte)(num >> 8);
		buffer[startRunPos + 3] = (byte)num;
		pSourceStream.Position = startRunPos + 4;
		await pSourceStream.WriteAsync(_cachedMemoryStream2.GetBuffer(), 0, count);
		pSourceStream.SetLength(pSourceStream.Position);
	}

	public static Task<string> ReadContentsAsync(string pFilePath)
	{
		return Task.Run(async () => await _readContentsAsync(pFilePath).ConfigureAwait(continueOnCapturedContext: false));
	}

	private static async Task<string> _readContentsAsync(string pFilePath)
	{
		string extension = Path.GetExtension(pFilePath);
		string text;
		switch (extension)
		{
		case ".ftk2z":
			text = LZ4Decompress(await FileIO.ReadAllBytes(pFilePath));
			break;
		case ".ftk2":
		case ".json":
			text = await FileIO.ReadAllText(pFilePath);
			break;
		default:
			throw new Exception("File format " + extension + " not supported");
		}
		if (extension == ".ftk2")
		{
			return _encryptOrDecrypt(text);
		}
		return text;
	}

	private static async Task<T> _readEncryptedFile<T>(string pFilePath, int pBufferSize)
	{
		using StreamReader sourceStream = await FileIO.OpenText(pFilePath);
		int capacity = (sourceStream.BaseStream.CanSeek ? ((int)sourceStream.BaseStream.Length + 1024) : pBufferSize);
		using MemoryStream decryptStream = new MemoryStream(capacity);
		using StreamWriter targetStream = new StreamWriter(decryptStream);
		int num = 0;
		while (!sourceStream.EndOfStream)
		{
			int num2 = sourceStream.Read();
			if (num2 < 0)
			{
				throw new Exception("[SaveDataHelper._readEncryptedFile] unexpected end of stream");
			}
			char pChar = (char)num2;
			pChar = _encryptOrDecryptChar(pChar, num);
			targetStream.Write(pChar);
			num++;
		}
		await targetStream.FlushAsync();
		decryptStream.Seek(0L, SeekOrigin.Begin);
		return await JsonHelper.DeserializeAsync<T>(decryptStream);
	}

	public static Task<T> ReadJsonAsync<T>(string pFilePath)
	{
		return Task.Run(async () => await _readJsonAsync<T>(pFilePath).ConfigureAwait(continueOnCapturedContext: false));
	}

	private static async Task<T> _readJsonAsync<T>(string pFilePath)
	{
		bool num = pFilePath.EndsWith(".ftk2");
		if (!num && !pFilePath.EndsWith(".json"))
		{
			throw new Exception("File format " + Path.GetExtension(pFilePath) + " not supported");
		}
		if (num)
		{
			return await _readEncryptedFile<T>(pFilePath, 65536);
		}
		using Stream stream = await FileIO.OpenRead(pFilePath);
		return await JsonHelper.DeserializeAsync<T>(stream);
	}

	public static Task<GameSaveDirector.GameSaveData> ReadRunSummaryAsync(string pFilePath)
	{
		return Task.Run(async () => await _readRunSummaryAsync(pFilePath).ConfigureAwait(continueOnCapturedContext: false));
	}

	private static async Task<GameSaveDirector.GameSaveData> _readRunSummaryAsync(string pFilePath)
	{
		bool flag = pFilePath.EndsWith(".ftk2z");
		bool isEncrypted = !flag && pFilePath.EndsWith(".ftk2");
		if (!flag && !isEncrypted && !pFilePath.EndsWith(".json"))
		{
			throw new Exception("File format " + Path.GetExtension(pFilePath) + " not supported");
		}
		GameSaveDirector.GameSaveData saveData = null;
		if (flag)
		{
			using Stream reader = await FileIO.OpenRead(pFilePath);
			int num = reader.ReadByte();
			int num2 = reader.ReadByte();
			int num3 = (num << 8) | num2;
			if (num3 > 0)
			{
				byte[] array = new byte[num3];
				reader.Read(array);
				using MemoryStream memStream = new MemoryStream(array);
				saveData = await JsonHelper.DeserializeAsync<GameSaveDirector.GameSaveData>(memStream);
			}
		}
		else
		{
			using StreamReader streamReader = await FileIO.OpenText(pFilePath);
			int num4 = 0;
			StringBuilder stringBuilder = new StringBuilder(1024);
			bool flag2 = false;
			while (!streamReader.EndOfStream)
			{
				char c = (char)streamReader.Read();
				if (isEncrypted)
				{
					c = _encryptOrDecryptChar(c, num4);
				}
				if (c == '\n')
				{
					flag2 = true;
					break;
				}
				stringBuilder.Append(c);
				num4++;
			}
			if (flag2)
			{
				stringBuilder.Replace("**//", string.Empty);
				stringBuilder.Replace("//**", string.Empty);
				saveData = JsonHelper.Deserialize<GameSaveDirector.GameSaveData>(stringBuilder.ToString());
			}
		}
		saveData.runPath = pFilePath;
		if (Application.platform == RuntimePlatform.PS5 && pFilePath.StartsWith("PS4_BACKWARDS_COMPAT:"))
		{
			saveData.runID = "ps4-" + saveData.runID;
		}
		return saveData;
	}

	public static Task<GameRunData> ReadRunDataAsync(string pFilePath)
	{
		return Task.Run(async () => await _readRunDataAsync(pFilePath).ConfigureAwait(continueOnCapturedContext: false));
	}

	private static async Task<GameRunData> _readRunDataAsync(string pFilePath)
	{
		bool flag = pFilePath.EndsWith(".ftk2z");
		bool isEncrypted = !flag && pFilePath.EndsWith(".ftk2");
		if (!flag && !isEncrypted && !pFilePath.EndsWith(".json"))
		{
			throw new Exception("File format " + Path.GetExtension(pFilePath) + " not supported");
		}
		try
		{
			GameRunData gameRunData = null;
			if (flag)
			{
				byte[] array = await FileIO.ReadAllBytes(pFilePath);
				byte num = array[0];
				int num2 = array[1];
				int num3 = ((num << 8) | num2) + 2;
				gameRunData = await GetRunFromCompressedBytes(array, num3, array.Length - num3);
			}
			else
			{
				using Stream fStream = await FileIO.OpenRead(pFilePath);
				gameRunData = ((!isEncrypted) ? (await JsonHelper.DeserializeAsync<GameRunData>(fStream)) : (await _readEncryptedFile<GameRunData>(pFilePath, 8388608)));
			}
			_tryRetrofitGameRun(gameRunData);
			gameRunData.Version = VersionHelper.GAME_VERSION;
			return gameRunData;
		}
		catch (Exception ex)
		{
			Debug.LogError("[SaveGameHelper._readRunDataAsync] Could not read data from file: " + pFilePath);
			Debug.LogError(ex);
			throw ex;
		}
	}

	public static async Task<GameRunData> GetRunFromCompressedBytes(byte[] pBytes, int pOffset, int pLength)
	{
		try
		{
			byte num = pBytes[pOffset];
			int num2 = pBytes[pOffset + 1];
			int num3 = pBytes[pOffset + 2];
			int num4 = pBytes[pOffset + 3];
			byte[] array = new byte[((num << 24) | (num2 << 16) | (num3 << 8) | num4) + 128];
			int count = LZ4Codec.Decode(pBytes, pOffset + 4, pLength - 4, array, 0, array.Length);
			using MemoryStream dataStream = new MemoryStream(array, 0, count, writable: false);
			return await JsonHelper.DeserializeAsync<GameRunData>(dataStream);
		}
		catch (Exception ex)
		{
			Debug.LogError("[SaveGameHelper.GetRunFromCompressedBytes] Failed to read data");
			throw ex;
		}
	}

	private static async Task<SaveDataObjects> _getSaveData(string pRunId, GameRunData pGameRun, UserData pUser)
	{
		StatsHelper.AddStat("TOTAL_LORE", pGameRun.ItemPools["CURRENCY_LORE"], StatsHelper.eStatType.GLOBAL);
		pGameRun.ItemPools["CURRENCY_LORE"] = 0;
		return await Task.Run(delegate
		{
			GameSaveDirector.GameSaveData runSummary = CreateGameSaveData(pRunId, pGameRun);
			return new SaveDataObjects
			{
				User = pUser,
				RunSummary = runSummary,
				RunData = pGameRun
			};
		});
	}

	public static async Task<bool> WriteManualSave(string pGameRunId, GameRunData pGameRun, string pSaveName, string pOverwriteFileName = null)
	{
		PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_manualsave_create", new Dictionary<string, object>
		{
			{
				"ADVENTURE",
				pGameRun?.ConfigName
			},
			{
				"DIFFICULTY",
				pGameRun?.GameDifficulty
			},
			{
				"IS_ONLINE",
				RouterHelper.Env.NetworkData.PlayingOnlineMultiplayer
			}
		}, "manualsave"));
		SaveDataObjects saveData = await _getSaveData(pGameRunId, pGameRun, null);
		Debug.Log("[SaveGameHelper.WriteManualSave] Saving manual gamerun " + pGameRunId);
		return await Task.Run(async delegate
		{
			_ = 1;
			try
			{
				string text;
				string pFilePath;
				if (!string.IsNullOrEmpty(pOverwriteFileName))
				{
					pFilePath = AssetLoader.TryGetExistingGameRunFilePath(pOverwriteFileName);
					text = pOverwriteFileName.Substring(37, pOverwriteFileName.Length - 37);
				}
				else
				{
					text = RouterHelper.Env.ManualSaveIdTracker.GetNextId(pGameRunId).ToString();
					string text2 = $"{pGameRunId}{'-'}{text}";
					pFilePath = AssetLoader.TryGetExistingGameRunFilePath(text2);
					if (string.IsNullOrEmpty(pFilePath))
					{
						pFilePath = AssetLoader.GetGameRunFilePath(text2);
					}
					else
					{
						Debug.LogError("[SaveGameHelper.WriteManualSave] Manual save already exists with name " + text2 + ", recalculating updated id");
						await RouterHelper.Env.ManualSaveIdTracker.CalculateIds();
						text = RouterHelper.Env.ManualSaveIdTracker.GetNextId(pGameRunId).ToString();
						text2 = $"{pGameRunId}{'-'}{text}";
						pFilePath = AssetLoader.TryGetExistingGameRunFilePath(text2);
						if (!string.IsNullOrEmpty(pFilePath))
						{
							Debug.LogError("[SaveGameHelper.WriteManualSave] Failed to recalculate new id: Manual save already exists with name " + text2 + ", unable to save");
							return false;
						}
						pFilePath = AssetLoader.GetGameRunFilePath(text2);
					}
				}
				saveData.RunSummary.manualId = text;
				saveData.RunSummary.saveName = pSaveName;
				await WriteRunDataAsync(pFilePath, saveData.RunSummary, saveData.RunData);
				return true;
			}
			catch (Exception message)
			{
				Debug.LogError(message);
				return false;
			}
		});
	}

	public static async Task<bool> WriteSaveData(string pGameRunId, GameRunData pGameRun, UserData pUser)
	{
		SaveDataObjects saveData = await _getSaveData(pGameRunId, pGameRun, pUser);
		Debug.Log("Saving gamerun " + pGameRunId);
		return await Task.Run(async delegate
		{
			_ = 2;
			try
			{
				string gameRunPath = AssetLoader.TryGetExistingGameRunFilePath(pGameRunId);
				if (string.IsNullOrEmpty(gameRunPath))
				{
					gameRunPath = AssetLoader.GetGameRunFilePath(pGameRunId);
				}
				await WriteUserDataAsync(UserDirectoryPath, saveData.User);
				await BackUpUser(UserDirectoryPath);
				await WriteRunDataAsync(gameRunPath, saveData.RunSummary, saveData.RunData);
				return true;
			}
			catch (Exception ex)
			{
				PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_save_fail", new Dictionary<string, object> { { "EXCEPTION", ex } }, "saveerror"));
				PlayfabHelper.TelemetryEvents.ForceSendQueuedEvents();
				Debug.LogError(ex);
				return false;
			}
		});
	}

	public static void DeleteSave(string pFileId)
	{
		string text = AssetLoader.GameRunsDirectoryPath();
		string text2 = AssetLoader.TryGetExistingGameRunFilePath(pFileId);
		if (text == null)
		{
			if (!string.IsNullOrEmpty(text2))
			{
				FileIOSync.Delete(Path.GetDirectoryName(text2));
			}
			return;
		}
		if (FileIOSync.Exists(text2))
		{
			FileIOSync.Delete(text2);
		}
		string gameRunImageFilePath = AssetLoader.GetGameRunImageFilePath(pFileId);
		if (FileIOSync.Exists(gameRunImageFilePath))
		{
			FileIOSync.Delete(gameRunImageFilePath);
		}
	}

	public static Task SaveUserAsync(UserData pUser)
	{
		return Task.Run(async delegate
		{
			await _saveUserAsync(pUser).ConfigureAwait(continueOnCapturedContext: false);
		});
	}

	private static async Task _saveUserAsync(UserData pUser)
	{
		_ = 1;
		try
		{
			await WriteUserDataAsync(UserDirectoryPath, pUser);
			await BackUpUser(UserDirectoryPath);
		}
		catch (Exception ex)
		{
			PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_save_user_fail", new Dictionary<string, object> { 
			{
				"EXCEPTION",
				ex.ToString()
			} }, "saveerror"));
			PlayfabHelper.TelemetryEvents.ForceSendQueuedEvents();
			throw ex;
		}
	}

	public static async Task BackUpUser(string pSourceFilePath)
	{
		string backupDirectoryPath = AssetLoader.BackupDirectoryPath();
		if (backupDirectoryPath == null)
		{
			return;
		}
		try
		{
			string sourceFileName = Path.GetFileNameWithoutExtension(pSourceFilePath);
			string extension = Path.GetExtension(pSourceFilePath);
			string backupFilePath = Path.Join(backupDirectoryPath, $"{sourceFileName}-backup-{Guid.NewGuid()}{extension}");
			await FileIO.Copy(pSourceFilePath, backupFilePath);
			Debug.Log("Backed up " + pSourceFilePath + " to " + backupFilePath);
			List<string> sourceFileBackups = (from f in Directory.GetFiles(backupDirectoryPath)
				where Path.GetFileNameWithoutExtension(f).StartsWith(sourceFileName)
				select f).ToList();
			while (sourceFileBackups.Count > 2)
			{
				string oldestBackup = sourceFileBackups.OrderBy((string pFileName) => File.GetLastWriteTime(pFileName)).First();
				await FileIO.Delete(oldestBackup);
				Debug.Log("Deleted old backup " + oldestBackup);
				sourceFileBackups.Remove(oldestBackup);
			}
		}
		catch (Exception message)
		{
			Debug.LogError("[SaveGameHelper.BackUp] Backing up file " + pSourceFilePath + " failed");
			Debug.LogError(message);
		}
	}

	public static bool Initialize(Env pEnv)
	{
		Debug.Log("[SaveGameHelper.Initialize] ENTERED");
		string userFilePath = AssetLoader.TryGetExistingUserSaveFilePath();
		_ = Application.version;
		bool flag = !string.IsNullOrEmpty(userFilePath);
		if (pEnv.GameRuns == null)
		{
			pEnv.GameRuns = new List<string>();
		}
		string text = AssetLoader.BackupDirectoryPath();
		if (text != null)
		{
			try
			{
				if (!Directory.Exists(text))
				{
					Directory.CreateDirectory(text);
				}
			}
			catch (Exception message)
			{
				Debug.LogError("[SaveGameHelper.Initialize] Failure on creating Backup Directory: " + text);
				Debug.LogError(message);
			}
		}
		string text2 = AssetLoader.GameRunsDirectoryPath();
		if (text2 != null)
		{
			try
			{
				if (!Directory.Exists(text2))
				{
					Directory.CreateDirectory(text2);
				}
			}
			catch (Exception message2)
			{
				Debug.LogError("[SaveGameHelper.Initialize] Failure on creating Gameruns Directory: " + text2);
				Debug.LogError(message2);
			}
		}
		bool flag2 = isABetaPlayer(userFilePath);
		if (flag && !flag2)
		{
			UserDirectoryPath = AssetLoader.TryGetExistingUserSaveFilePath();
			Debug.Log("User is present.");
			Debug.Log("Reading user data at " + userFilePath);
			try
			{
				pEnv.User = UserData.Create(ReadJsonAsync<JsonElement>(userFilePath).Result);
			}
			catch (Exception ex)
			{
				PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_load_user_fail", new Dictionary<string, object> { 
				{
					"EXCEPTION",
					ex.ToString()
				} }, "saveerror"));
				PlayfabHelper.TelemetryEvents.ForceSendQueuedEvents();
				Debug.LogError("[SaveGameHelper.Initialize] Failed to load UserData, trying backups");
				Debug.LogError(ex);
				pEnv.User = _recoverUserDataFromBackup();
			}
			pEnv.GameRuns = (from c in ListGameRunsSync()
				select c.GameRunId).Distinct().ToList();
		}
		else
		{
			PlayerPrefs.DeleteAll();
			if (flag2)
			{
				try
				{
					FileIOSync.Delete(userFilePath);
				}
				catch (Exception message3)
				{
					Debug.LogError("[SaveGameHelper.Initialize] Caught exception when attempting to delete beta player's file at: '" + userFilePath + "'. Exception Follows:");
					Debug.Log(message3);
				}
				deleteAllGameRuns();
			}
			pEnv.User = _createNewUser();
			UserDirectoryPath = AssetLoader.GetNewUserSaveFilePath();
		}
		SaveUserAsync(pEnv.User).Wait();
		_checkSaveGameMigration();
		string s = JsonHelper.Serialize(pEnv.User, pIndented: true);
		int byteCount = Encoding.UTF8.GetByteCount(s);
		PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_user_size", new Dictionary<string, object> { { "SIZE", byteCount } }));
		return flag;
		static void deleteAllGameRuns()
		{
			string path = AssetLoader.BackupDirectoryPath();
			try
			{
				if (Directory.Exists(path))
				{
					Directory.Delete(path);
					Directory.CreateDirectory(path);
				}
			}
			catch (Exception message4)
			{
				Debug.LogError(message4);
				try
				{
					foreach (string item in Directory.EnumerateFiles(path))
					{
						FileIOSync.Delete(item);
					}
				}
				catch (Exception message5)
				{
					Debug.LogError(message5);
				}
			}
		}
		bool isABetaPlayer(string pUserFilePath)
		{
			if (PublishPlatformHelper.Platform.PlatformId == ePlatformIds.PSN || PublishPlatformHelper.Platform.PlatformId == ePlatformIds.XBOX)
			{
				return false;
			}
			try
			{
				string text3 = FileIOSync.ReadAllText(userFilePath);
				bool flag3 = Path.GetExtension(userFilePath) == ".json";
				bool flag4 = string.IsNullOrEmpty(text3);
				bool flag5 = text3.StartsWith("I");
				Debug.Log($"[SaveGameHelper.isABetaPlayer] Checking beta conditions: isJson'{flag3}', isNullOrEmpty'{flag4}', startsWithI'{flag5}'");
				return Path.GetExtension(userFilePath) == ".json" && (string.IsNullOrEmpty(text3) || text3.StartsWith("I"));
			}
			catch (Exception message4)
			{
				Debug.LogError("[SaveGameHelper.isABetaPlayer] Caught exception when attempting to deserialize file at: '" + userFilePath + "'. Exception Follows:");
				Debug.Log(message4);
				return false;
			}
		}
	}

	private static UserData _recoverUserDataFromBackup()
	{
		bool flag = false;
		UserData result = null;
		string text = AssetLoader.BackupDirectoryPath();
		if (text == null || !Directory.Exists(text))
		{
			Debug.LogError("There is no user backups directory");
			return _createNewUser();
		}
		List<string> list = (from f in Directory.GetFiles(text)
			where Path.GetFileNameWithoutExtension(f).StartsWith("User")
			select f).ToList();
		if (list.Count < 1)
		{
			Debug.LogError("There are no user backups");
		}
		else
		{
			foreach (string item in list.OrderByDescending((string f) => File.GetLastWriteTime(f)))
			{
				try
				{
					result = UserData.Create(ReadJsonAsync<JsonElement>(item).Result);
					flag = true;
				}
				catch (Exception message)
				{
					Debug.LogError("[SaveGameHelper._recoverUserDataFromBackup] Failed to load backup " + item + ", deleting it");
					Debug.LogError(message);
					try
					{
						FileIOSync.Delete(item);
					}
					catch (Exception message2)
					{
						Debug.LogError("[SaveGameHelper._recoverUserDataFromBackup] Failed to delete " + item);
						Debug.LogError(message2);
					}
				}
				if (flag)
				{
					Debug.Log("Succesfully loaded userfile " + item + " from backup!");
					break;
				}
			}
		}
		if (flag)
		{
			return result;
		}
		return _createNewUser();
	}

	private static UserData _createNewUser()
	{
		return UserData.Create();
	}

	public static UserData CreateDebugUser()
	{
		UserData userData = UserData.Create();
		userData.ShouldAutoEndTurn = false;
		return userData;
	}

	private static void _checkSaveGameMigration()
	{
		List<string> list = new List<string>();
		List<(string, string)> list2 = new List<(string, string)>();
		foreach (string item in list)
		{
			string text = AssetLoader.TryGetExistingGameRunFilePath(item);
			string text2 = null;
			try
			{
				_ = ReadRunSummaryAsync(text).Result;
			}
			catch (Exception)
			{
				text2 = null;
				Debug.LogError("[SaveGameHelper._checkSaveGameMigration] Could not read file: " + text);
			}
			if (text2 != null && !text2.StartsWith("//**"))
			{
				list2.Add((item, text));
			}
		}
		if (list2.Count <= 0)
		{
			return;
		}
		Debug.Log($"[SaveGameHelper._checkSaveGameMigration] Migrating {list2.Count} save games due to missing summaries on first line");
		foreach (var item2 in list2)
		{
			try
			{
				GameRunData result = ReadRunDataAsync(item2.Item2).Result;
				GameSaveDirector.GameSaveData gameSaveData = CreateGameSaveData(item2.Item1, result);
				_getGameSaveDataString(gameSaveData);
				FileIOSync.ReadAllText(item2.Item2);
				string tempFileName = Path.GetTempFileName();
				WriteRunDataAsync(tempFileName, gameSaveData, result).Wait();
				FileIOSync.Copy(tempFileName, item2.Item2, overwrite: true);
				FileIOSync.Delete(tempFileName);
			}
			catch (Exception)
			{
				Debug.Log("[SaveGameHelper._checkSaveGameMigration] Could not migrate file: " + item2.Item2);
			}
		}
	}

	public static async Task<List<GameSaveDirector.GameSaveData>> GetAllGameSaveData(bool pIncludePS4TransferSaves = false)
	{
		List<GameSaveDirector.GameSaveData> gameSaves = new List<GameSaveDirector.GameSaveData>();
		List<GameRunFileInfo> runInfoes = await ListGameRuns();
		if (pIncludePS4TransferSaves)
		{
			List<GameRunFileInfo> list = runInfoes;
			list.AddRange(await ListPS4TransferRuns());
		}
		foreach (GameRunFileInfo runInfo in runInfoes)
		{
			string pFilePath = AssetLoader.TryGetExistingGameRunFilePath(runInfo.FileName);
			try
			{
				GameSaveDirector.GameSaveData gameSaveData = await ReadRunSummaryAsync(pFilePath);
				if (string.IsNullOrEmpty(gameSaveData.runID))
				{
					Debug.LogError("[SaveGameHelper.GetAllGameSaveData] Unable to load run with file name " + runInfo.FileName);
					continue;
				}
				Lang.__t("LOAD_GAME_UI_VERSION_ERROR");
				if (!string.IsNullOrEmpty(gameSaveData.version))
				{
					_ = gameSaveData.version;
				}
				gameSaves.Add(gameSaveData);
			}
			catch (Exception arg)
			{
				Debug.LogError($"[SaveGameHelper.GetAllGameSaveData] Error attempting to load run with name {runInfo.FileName}: {arg}");
			}
		}
		int num = gameSaves.Count((GameSaveDirector.GameSaveData s) => !string.IsNullOrEmpty(s.manualId) && !s.IsPS4TransferRun());
		PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_manualsave_count", new Dictionary<string, object> { { "COUNT", num } }, "manualsave"));
		return (from s in gameSaves
			orderby s.IsPS4TransferRun(), s.dateTime descending
			select s).ToList();
	}

	public static GameSaveDirector.GameSaveData CreateGameSaveData(string pRunId, GameRunData pGameRun)
	{
		GameSaveDirector.GameSaveData gameSaveData = new GameSaveDirector.GameSaveData
		{
			adventureType = pGameRun.ConfigName,
			dateTime = DateTime.Now,
			runID = pRunId,
			version = pGameRun.Version,
			saveName = "",
			loopCount = ((pGameRun.DungeonState != null && pGameRun.DungeonState.LoopState != null) ? pGameRun.DungeonState.LoopState.TotalLoops : 0),
			roomCount = ((pGameRun.DungeonState != null && pGameRun.DungeonState.LoopState != null) ? (pGameRun.DungeonState.RoomHistory.Count - (pGameRun.DungeonState.LoopState.TotalLoops + 1)) : 0),
			roundCount = ((pGameRun.RoundCount > pGameRun.AdventureState.TotalRoundCount) ? pGameRun.RoundCount : pGameRun.AdventureState.TotalRoundCount),
			chaosState = pGameRun.AdventureState.MapState.ChaosState,
			currentLifePool = pGameRun.CurrentLifePool,
			maxLifePool = AdventureHelper.GetWorldModifier(eWorldModifiers.LIFE_POOL_MAX, pGameRun),
			difficulty = pGameRun.GameDifficulty,
			mapGenSeed = pGameRun.MapGenSeed,
			characters = new List<GameSaveDirector.CharacterData>(),
			expansions = new List<eExpansions>()
		};
		foreach (Entity item in pGameRun.Entities.FindAll((Entity e) => e.Has<CharacterComponent>() && e.Has<PlayerComponent>()))
		{
			CharacterComponent characterComponent = item.Get<CharacterComponent>();
			CharacterHelper.GetFirstTrait(characterComponent);
			gameSaveData.characters.Add(new GameSaveDirector.CharacterData
			{
				configName = characterComponent.ConfigName,
				displayName = characterComponent.DisplayName,
				level = ProgressionHelper.GetEntityLevel(item),
				traitId = CharacterHelper.GetFirstTrait(characterComponent),
				nomenclator = characterComponent.Nomenclator
			});
		}
		if (pGameRun.Expansions != null)
		{
			foreach (eExpansions expansion in pGameRun.Expansions)
			{
				gameSaveData.expansions.Add(expansion);
			}
		}
		return gameSaveData;
	}

	private static string _getGameSaveDataString(GameSaveDirector.GameSaveData pGameSave)
	{
		return "//**" + JsonHelper.Serialize(pGameSave) + "**//";
	}

	public static async Task MigrateUserSettings(Env pEnv)
	{
		if (PlayerPrefs.HasKey("PREF_ARACHNOPHOBIA"))
		{
			pEnv.User.ArachnophobiaModeEnabled = PlayerPrefs.GetInt("PREF_ARACHNOPHOBIA") == 1;
			PlayerPrefs.DeleteKey("PREF_ARACHNOPHOBIA");
		}
		if (PlayerPrefs.HasKey("PREF_LANG"))
		{
			pEnv.User.Language = PlayerPrefs.GetString("PREF_LANG");
			PlayerPrefs.DeleteKey("PREF_LANG");
		}
		if (PlayerPrefs.HasKey("PREF_MASTER_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_MASTER_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_MASTER_VOLUME", PlayerPrefs.GetFloat("PREF_MASTER_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_MASTER_VOLUME");
		}
		if (PlayerPrefs.HasKey("PREF_SFX_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_SFX_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_SFX_VOLUME", PlayerPrefs.GetFloat("PREF_SFX_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_SFX_VOLUME");
		}
		if (PlayerPrefs.HasKey("PREF_UI_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_UI_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_UI_VOLUME", PlayerPrefs.GetFloat("PREF_UI_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_UI_VOLUME");
		}
		if (PlayerPrefs.HasKey("PREF_MUSIC_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_MUSIC_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_MUSIC_VOLUME", PlayerPrefs.GetFloat("PREF_MUSIC_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_MUSIC_VOLUME");
		}
		if (PlayerPrefs.HasKey("PREF_VOICE_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_VOICE_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_VOICE_VOLUME", PlayerPrefs.GetFloat("PREF_VOICE_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_VOICE_VOLUME");
		}
		if (PlayerPrefs.HasKey("PREF_ENVIRONMENT_VOLUME"))
		{
			if (!pEnv.User.VolumeOptions.ContainsKey("PREF_ENVIRONMENT_VOLUME"))
			{
				pEnv.User.VolumeOptions.Add("PREF_ENVIRONMENT_VOLUME", PlayerPrefs.GetFloat("PREF_ENVIRONMENT_VOLUME"));
			}
			PlayerPrefs.DeleteKey("PREF_ENVIRONMENT_VOLUME");
		}
		if (!PlayerPrefs.HasKey("RESET_BINDINGS") || PlayerPrefs.GetString("RESET_BINDINGS") == "TRUE")
		{
			pEnv.User.overrideBindingsJSON = null;
			InputController.Instance.InputActions.RemoveAllBindingOverrides();
			PlayerPrefs.SetString("RESET_BINDINGS", "FALSE");
		}
		await SaveUserAsync(pEnv.User);
	}

	public static void MigrateUserStats(UserData pUserData)
	{
		foreach (KeyValuePair<string, int> item in LORE_STORE_REFUND)
		{
			if (pUserData.LocalStats.ContainsKey(item.Key))
			{
				if (pUserData.LocalStats[item.Key] == 1)
				{
					pUserData.LocalStats.TryAdd("TOTAL_LORE", 0);
					pUserData.LocalStats["TOTAL_LORE"] = pUserData.LocalStats["TOTAL_LORE"] + item.Value;
				}
				pUserData.LocalStats.Remove(item.Key);
			}
		}
		foreach (var item2 in MIGRATE_USER_STATS_NEW_ID)
		{
			if (pUserData.LocalStats.TryGetValue(item2.oldID, out var value))
			{
				pUserData.LocalStats.Remove(item2.oldID);
				pUserData.LocalStats[item2.newID] = value;
			}
		}
		int num = 0;
		foreach (string item3 in pUserData.LocalStats.Keys.ToList())
		{
			if (item3.StartsWith("ITEMS_COLLECTED~PLAYER~") || item3.StartsWith("GOLD_COLLECTED~PLAYER~"))
			{
				num++;
				pUserData.LocalStats.Remove(item3);
			}
		}
		if (num > 0)
		{
			PlayfabHelper.TelemetryEvents.AddEvent(new TelemetryEvent("iog_user_guid_stats_removed", new Dictionary<string, object> { { "COUNT", num } }));
		}
	}

	private static void _tryRetrofitGameRun(GameRunData pGameRun)
	{
		GameRunData gameRunData = pGameRun;
		if (gameRunData.PlayerFollowers == null)
		{
			gameRunData.PlayerFollowers = new Dictionary<string, FollowerState>();
		}
		gameRunData = pGameRun;
		if (gameRunData.QuestViewDataCache == null)
		{
			gameRunData.QuestViewDataCache = new Dictionary<string, ParseTextResult>();
		}
		gameRunData = pGameRun;
		if (gameRunData.ItemPools == null)
		{
			gameRunData.ItemPools = new Dictionary<string, int>();
		}
		pGameRun.ItemPools.TryAdd("CURRENCY_LORE", 0);
		if (pGameRun.AdventureState != null)
		{
			AdventureState adventureState = pGameRun.AdventureState;
			if (adventureState.StrandedVehicles == null)
			{
				adventureState.StrandedVehicles = new List<string>();
			}
			adventureState = pGameRun.AdventureState;
			if (adventureState.SkillProcsTurn == null)
			{
				adventureState.SkillProcsTurn = new Dictionary<eSkills, SkillProcHistoryData>();
			}
			adventureState = pGameRun.AdventureState;
			if (adventureState.AmbushModifiers == null)
			{
				adventureState.AmbushModifiers = AdventureHelper.InitializeAmbushModifiers();
			}
		}
		_tryRetrofitSubMapStates(pGameRun);
		if (CompareVersion(pGameRun.Version, "1.12.9") < 0)
		{
			Dictionary<string, MapState> mapStates = pGameRun.AdventureState.MapStates;
			if (mapStates != null && mapStates.Count > 0)
			{
				foreach (KeyValuePair<string, MapState> mapState in pGameRun.AdventureState.MapStates)
				{
					MapState value = mapState.Value;
					if (value.HexPropertyCooldown == null)
					{
						value.HexPropertyCooldown = new List<(string, eHexProperties, int)>();
					}
					value = mapState.Value;
					if (value.EnemiesToSpawnOnNextTrickle == null)
					{
						value.EnemiesToSpawnOnNextTrickle = new List<EnemyTrickleData>();
					}
					value = mapState.Value;
					if (value.EncountersToSpawnOnNextTrickle == null)
					{
						value.EncountersToSpawnOnNextTrickle = new List<EncounterTrickleData>();
					}
					value = mapState.Value;
					if (value.WorldModifiers == null)
					{
						value.WorldModifiers = new Dictionary<eWorldModifiers, int>();
					}
					foreach (KeyValuePair<eWorldModifiers, int> dEFAULT_WORLD_MODIFIER in AdventureHelper.DEFAULT_WORLD_MODIFIERS)
					{
						mapState.Value.WorldModifiers.TryAdd(dEFAULT_WORLD_MODIFIER.Key, dEFAULT_WORLD_MODIFIER.Value);
					}
					Dictionary<eWorldModifiers, int> worldModifiers = pGameRun.WorldModifiers;
					if (worldModifiers == null || worldModifiers.Count <= 0)
					{
						continue;
					}
					foreach (KeyValuePair<eWorldModifiers, int> worldModifier in pGameRun.WorldModifiers)
					{
						mapState.Value.WorldModifiers[worldModifier.Key] = worldModifier.Value;
					}
					List<eWorldModifiers> list = new List<eWorldModifiers>();
					foreach (KeyValuePair<eWorldModifiers, int> worldModifier2 in pGameRun.WorldModifiers)
					{
						if (worldModifier2.Key != eWorldModifiers.LIFE_POOL_MAX)
						{
							list.Add(worldModifier2.Key);
						}
					}
					foreach (eWorldModifiers item in list)
					{
						pGameRun.WorldModifiers.Remove(item);
					}
				}
				pGameRun.WorldModifiers?.Clear();
			}
		}
		CharacterComponent pComponent5;
		if (CompareVersion(pGameRun.Version, "1.1.65") < 0 && _retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
		{
			foreach (EncounterComponent item2 in (from x in pGameRun.Entities.FindAll((Entity x) => x.TryGet<EncounterComponent>(out pComponent5) && pComponent5.Type == eEncounterTypes.DUNGEON)
				select x.Get<EncounterComponent>()).ToList())
			{
				item2.DontRemoveEntityOnDecay = true;
				item2.RemoveEncounterAfterCombat = eEncounterRemove.NONE;
			}
		}
		if ((CompareVersion(pGameRun.Version, "1.1.75") < 0 || CompareVersion(pGameRun.Version, "1.1.85") < 0) && new List<string> { "STORY_1_3", "STORY_1_4", "STORY_1_5" }.Contains(pGameRun.ConfigName))
		{
			pGameRun.Entities.RemoveAll((Entity x) => x.Guid == "BOSS_TARGET");
		}
		if (CompareVersion(pGameRun.Version, "1.1.118") < 0)
		{
			MapState value = pGameRun.AdventureState.MapState;
			if (value.CustomTimelineEvents == null)
			{
				value.CustomTimelineEvents = new Dictionary<int, List<TimelineEventData>>();
			}
			value = pGameRun.AdventureState.MapState;
			if (value.ExpiredCustomTimelineEvents == null)
			{
				value.ExpiredCustomTimelineEvents = new Dictionary<int, List<TimelineEventData>>();
			}
		}
		if (CompareVersion(pGameRun.Version, "1.2.1") < 0)
		{
			if (pGameRun.VenueState != null && pGameRun.VenueState.Venue != null)
			{
				VenueData venue = pGameRun.VenueState.Venue;
				if (venue.PhasesData == null)
				{
					venue.PhasesData = new List<ProcessedPhaseData>();
				}
			}
			if (pGameRun.DungeonState != null)
			{
				DungeonState dungeonState = pGameRun.DungeonState;
				if (dungeonState.FilteredChoicePool == null)
				{
					dungeonState.FilteredChoicePool = new List<string>();
				}
				dungeonState = pGameRun.DungeonState;
				if (dungeonState.RoomHistory == null)
				{
					dungeonState.RoomHistory = new List<AdventureSummaryViewHelper.eRoomType>();
				}
				dungeonState = pGameRun.DungeonState;
				if (dungeonState.RoomPresetBags == null)
				{
					dungeonState.RoomPresetBags = new Dictionary<eDungeonRoomPreset, List<DungeonRoomConfig>>();
				}
			}
			if (_retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
			{
				if (pGameRun != null && pGameRun.VenueState != null && pGameRun.VenueState.Venue != null)
				{
					pGameRun.VenueState.Venue.PhasesData.Clear();
					GameRunData gameRunData2 = pGameRun;
					if (gameRunData2 != null && gameRunData2.VenueState?.Venue?.Phases?.Count > 0)
					{
						foreach (var phase in pGameRun.VenueState.Venue.Phases)
						{
							pGameRun.VenueState.Venue.PhasesData.Add(DungeonHelper.CreateProcessedPhaseData(phase.Item1, phase.Item2));
						}
						pGameRun.VenueState.Venue.Phases = null;
					}
				}
				if (pGameRun != null && pGameRun.DungeonState != null)
				{
					List<VenueData> ongoingVenues = pGameRun.DungeonState.OngoingVenues;
					if (ongoingVenues != null && ongoingVenues.Count > 0)
					{
						if (pGameRun.DungeonState.OngoingVenues.Last().DioramaName == "BLACKOUT")
						{
							int num = pGameRun.DungeonState.OngoingVenues.IndexOf(pGameRun.DungeonState.OngoingVenues.Last());
							if (pGameRun.DungeonState.OngoingVenues.Count - 1 >= num && pGameRun.DungeonState.OngoingVenues[num - 1].DioramaName == "BLACKOUT")
							{
								pGameRun.DungeonState.OngoingVenues.RemoveAt(num);
							}
						}
						foreach (VenueData ongoingVenue in pGameRun.DungeonState.OngoingVenues)
						{
							VenueData venue = ongoingVenue;
							if (venue.PhasesData == null)
							{
								venue.PhasesData = new List<ProcessedPhaseData>();
							}
							ongoingVenue.PhasesData.Clear();
							List<(ePhases, object)> phases = ongoingVenue.Phases;
							if (phases == null || phases.Count <= 0)
							{
								continue;
							}
							foreach (var phase2 in ongoingVenue.Phases)
							{
								if (phase2.Item1 == ePhases.ENCOUNTER)
								{
									List<string> pArgs = new List<string> { phase2.Item2.ToString() };
									ongoingVenue.PhasesData.Add(DungeonHelper.CreateProcessedPhaseData(phase2.Item1, pArgs));
								}
								else if (phase2.Item1 == ePhases.TREASURE)
								{
									if (phase2.Item2.GetType() == typeof(JsonElement))
									{
										TreasureConfig treasureConfig = JsonHelper.Deserialize<TreasureConfig>(((JsonElement)phase2.Item2).GetRawText());
										treasureConfig.MimicName = (string.IsNullOrEmpty(treasureConfig.MimicName) ? "MIMIC_GENERIC_00" : treasureConfig.MimicName);
										ongoingVenue.PhasesData.Add(DungeonHelper.CreateProcessedPhaseData(phase2.Item1, treasureConfig));
									}
								}
								else
								{
									ongoingVenue.PhasesData.Add(DungeonHelper.CreateProcessedPhaseData(phase2.Item1, phase2.Item2));
								}
							}
							ongoingVenue.Phases = null;
						}
					}
				}
			}
		}
		List<string> badDungeonIDs;
		if (CompareVersion(pGameRun.Version, "1.2.0") < 0)
		{
			badDungeonIDs = new List<string> { "CELLAR_*_DUNGEON", "CRYPT_*_DUNGEON", "DARK_CAVE_*_DUNGEON", "FIRE_CAVE_*_DUNGEON", "MANOR_*_DUNGEON", "MINES_*_DUNGEON", "SEA_CAVE_*_DUNGEON", "SPIDER_CAVE_*_DUNGEON" };
			if (_retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
			{
				foreach (Entity item3 in pGameRun.Entities.FindAll((Entity x) => x.TryGet<EncounterComponent>(out pComponent5) && pComponent5.Type == eEncounterTypes.DUNGEON).ToList())
				{
					if (item3.TryGet<DungeonEncounterComponent>(out var pComponent))
					{
						pComponent.DungeonID = _fixDungeonID(pComponent.DungeonID);
					}
				}
				GameRunData gameRunData3 = pGameRun;
				if (gameRunData3 != null && gameRunData3.DungeonState?.ConfigNames?.Count > 0)
				{
					for (int num2 = 0; num2 < pGameRun.DungeonState.ConfigNames.Count; num2++)
					{
						pGameRun.DungeonState.ConfigNames[num2] = _fixDungeonID(pGameRun.DungeonState.ConfigNames[num2]);
					}
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.2.0") < 0 && _retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
		{
			foreach (Entity item4 in pGameRun.Entities.FindAll((Entity x) => x.TryGet<EncounterComponent>(out pComponent5) && pComponent5.Type == eEncounterTypes.HAUNT && !pComponent5.Properties.Contains(eEncounterProperties.COMPLETED)))
			{
				QuestData killScourgeQuest = ScourgeHelper.CreateKillScourgeQuest(item4.Get<HauntComponent>().Scourge, item4);
				if (!pGameRun.ActiveQuests.Any((QuestState x) => x.Data.ID == killScourgeQuest.ID) && !pGameRun.CompletedQuests.Any((QuestState x) => x.Data.ID == killScourgeQuest.ID))
				{
					killScourgeQuest.Hidden = true;
					pGameRun.ActiveQuests.Add(QuestHelper.CreateQuestState(killScourgeQuest));
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.2.23") < 0)
		{
			foreach (Entity item5 in pGameRun.Entities.Where(delegate(Entity x)
			{
				if (x.TryGet<CharacterComponent>(out pComponent5))
				{
					List<Thing> things = pComponent5.Things;
					if (things == null)
					{
						return false;
					}
					return things.Count > 0;
				}
				return false;
			}))
			{
				foreach (Thing thing2 in item5.Get<CharacterComponent>().Things)
				{
					if (CoreHelper.TryGetCustomData(thing2, "MATERIAL", out var pValue))
					{
						switch (pValue)
						{
						case "ATT_LEATHER":
							pValue = "ATT_LEATHERA";
							break;
						case "ATT_LIGHT_LEATHER":
							pValue = "ATT_LIGHTLEATHER";
							break;
						case "ATT_CURED_LEATHER":
							pValue = "ATT_CUREDLEATHER";
							break;
						default:
							continue;
						}
						CoreHelper.SetCustomData(thing2, "MATERIAL", pValue);
					}
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.2.3") < 0 && _retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
		{
			_convertToPreviousQuestID(pGameRun.ActiveQuests);
			_convertToPreviousQuestID(pGameRun.CompletedQuests);
			_convertToPreviousQuestID(pGameRun.FailedQuests);
			GameRandom gameRandom = new GameRandom();
			foreach (HexComponent item6 in (from x in pGameRun.Entities
				where x.Has<HexComponent>()
				select x.Get<HexComponent>()).ToList())
			{
				if (item6.Seed <= 0)
				{
					item6.Seed = gameRandom.NextInt(1, 1000000);
				}
				if (item6.HexProperties.Contains(eHexProperties.SEASHALLOW))
				{
					item6.ElevationLayer = -3;
				}
				else if (item6.HexProperties.Contains(eHexProperties.SEADEEP))
				{
					item6.ElevationLayer = -6;
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.8.0") < 0 && _retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
		{
			foreach (VehicleComponent item7 in (from x in pGameRun.Entities
				where x.Has<VehicleComponent>()
				select x.Get<VehicleComponent>()).ToList())
			{
				item7.CanMove = true;
			}
		}
		if (CompareVersion(pGameRun.Version, "1.2.53") < 0)
		{
			foreach (Entity item8 in pGameRun.Entities.Where(delegate(Entity x)
			{
				if (x.TryGet<CharacterComponent>(out pComponent5))
				{
					List<Thing> things = pComponent5.Things;
					if (things == null)
					{
						return false;
					}
					return things.Count > 0;
				}
				return false;
			}))
			{
				item8.Get<CharacterComponent>().Things.RemoveAll((Thing t) => t.ConfigName.StartsWith("SKILL_"));
			}
		}
		List<Entity> list2 = pGameRun.Entities.FindAll((Entity e) => e.Has<PlayerComponent>());
		foreach (Entity item9 in list2)
		{
			List<eEquipmentSlots> list3 = new List<eEquipmentSlots>();
			CharacterComponent characterComponent = item9.Get<CharacterComponent>();
			foreach (var (eEquipmentSlots3, value2) in characterComponent.Equipped)
			{
				if (!string.IsNullOrEmpty(value2) && EquipmentHelper.GetEquippedThingBySlot(eEquipmentSlots3, item9) == null)
				{
					list3.Add(eEquipmentSlots3);
				}
			}
			foreach (eEquipmentSlots item10 in list3)
			{
				Debug.LogError($"Player {item9} has non-existent item in {item10}, removing it");
				characterComponent.Equipped[item10] = "";
			}
		}
		if (CompareVersion(pGameRun.Version, "1.8.13") < 0)
		{
			Dictionary<string, MapState> mapStates2 = pGameRun.AdventureState.MapStates;
			if (mapStates2 != null && mapStates2.Count > 0)
			{
				foreach (KeyValuePair<string, MapState> map in pGameRun.AdventureState.MapStates)
				{
					pGameRun.Entities.FindAll((Entity x) => x.TryGet<AdventureComponent>(out pComponent5) && pComponent5.MapID == map.Key && x.TryGet<HexComponent>(out var pComponent6) && pComponent6.HexProperties.Contains(eHexProperties.BORDER));
					(int, int) mapSize = HexHelper.GetMapSize(pGameRun, map.Key);
					List<Entity>[,] array = HexHelper.CreateMiniHexMap(pGameRun.Entities, pGameRun, mapSize.Item2 + 1, mapSize.Item1 + 1, map.Key);
					for (int num3 = 0; num3 < array.GetLength(0); num3++)
					{
						for (int num4 = 0; num4 < array.GetLength(1); num4++)
						{
							Entity entity = array[num3, num4].FirstOrDefault((Entity e) => e.Has<HexComponent>());
							if (entity != null)
							{
								MapGenHelper.FixUnreachableHexes(entity, array, null);
							}
						}
					}
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.8.0") < 0 && new List<string> { "STORY_1_1", "STORY_1_2", "STORY_1_3", "STORY_1_4", "STORY_1_5" }.Contains(pGameRun.ConfigName))
		{
			GameRandom pGameRandom = new GameRandom();
			foreach (WeatherComponent item11 in (from x in pGameRun.Entities
				where x.Has<WeatherComponent>()
				select x.Get<WeatherComponent>()).ToList())
			{
				item11.Global = true;
			}
			RouterHelper.Env.GameRun = pGameRun;
			RouterHelper.Env.HexMaps = new Dictionary<string, List<Entity>[,]>();
			AdventureHelper.LoadAllMapsToHexMaps(RouterHelper.Env);
			string activeMapID = pGameRun.AdventureState.ActiveMapID;
			foreach (string key2 in pGameRun.AdventureState.MapStates.Keys)
			{
				pGameRun.AdventureState.ActiveMapID = key2;
				WeatherHelper.InitializeWeathers(RouterHelper.Env, Env.Configs.Adventures[pGameRun.ConfigName].MapZones, pGameRandom);
			}
			pGameRun.AdventureState.ActiveMapID = activeMapID;
			RouterHelper.Env.HexMaps = null;
			RouterHelper.Env.GameRun = null;
		}
		if (pGameRun.Expansions == null || pGameRun.Expansions.Count == 0)
		{
			pGameRun.Expansions = new List<eExpansions> { eExpansions.BASE };
			eExpansions[] array2 = (eExpansions[])Enum.GetValues(typeof(eExpansions));
			switch (PublishPlatformHelper.Platform.PlatformId)
			{
			case ePlatformIds.STEAM:
			{
				eExpansions[] array3 = array2;
				foreach (eExpansions eExpansions3 in array3)
				{
					if (PublishPlatformDLCProduct.GetDLCProduct(ePlatformIds.STEAM, eExpansions3) == "-1" || (eExpansions3 == eExpansions.PRIMORDIAL && StatsHelper.GetStat(string.Format("{0}{1}", "EXPANSION_OWNED_", eExpansions.PRIMORDIAL), StatsHelper.eStatType.LOCAL) == 1))
					{
						pGameRun.Expansions.Add(eExpansions3);
					}
				}
				break;
			}
			case ePlatformIds.PSN:
			{
				eExpansions[] array3 = array2;
				foreach (eExpansions eExpansions4 in array3)
				{
					if (PublishPlatformDLCProduct.GetDLCProduct(ePlatformIds.PSN, eExpansions4) == "-1")
					{
						pGameRun.Expansions.Add(eExpansions4);
					}
				}
				break;
			}
			case ePlatformIds.XBOX:
			{
				eExpansions[] array3 = array2;
				foreach (eExpansions eExpansions2 in array3)
				{
					if (PublishPlatformDLCProduct.GetDLCProduct(ePlatformIds.XBOX, eExpansions2) == "-1")
					{
						pGameRun.Expansions.Add(eExpansions2);
					}
				}
				break;
			}
			default:
				GameRunData.SetDefaultExpansions(pGameRun);
				break;
			}
		}
		if (CompareVersion(pGameRun.Version, "1.8.9") < 0)
		{
			foreach (Entity item12 in pGameRun.Entities.FindAll((Entity x) => x.TryGet<EncounterComponent>(out pComponent5) && pComponent5.Type == eEncounterTypes.SKILL && x.Has<SkillEncounterComponent>()))
			{
				SkillEncounterComponent skillEncounterComponent = item12.Get<SkillEncounterComponent>();
				if (!Env.Configs.SkillEncounters.ContainsKey(skillEncounterComponent.SkillEncounterID))
				{
					pGameRun.Entities.Remove(item12);
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.10.4") < 0)
		{
			foreach (Entity item13 in pGameRun.Entities.FindAll((Entity x) => x.Has<MarketEncounterComponent>()))
			{
				_parseThings(item13.Get<MarketEncounterComponent>().MarketItems);
			}
			foreach (Entity item14 in pGameRun.Entities.FindAll((Entity x) => x.Has<CharacterComponent>()))
			{
				_parseThings(item14.Get<CharacterComponent>().Things, item14);
			}
		}
		List<(string, string)> weaponConfigNameChanges;
		if (CompareVersion(pGameRun.Version, "1.10.10") < 0)
		{
			weaponConfigNameChanges = new List<(string, string)> { ("GUN_GOLDEN_LIGHT_00", "GUN_GOLDEN_TINY_00") };
			foreach (Entity item15 in pGameRun.Entities.FindAll((Entity x) => x.Has<MarketEncounterComponent>()))
			{
				_parseThings2(item15.Get<MarketEncounterComponent>().MarketItems);
			}
			foreach (Entity item16 in pGameRun.Entities.FindAll((Entity x) => x.Has<CharacterComponent>()))
			{
				_parseThings2(item16.Get<CharacterComponent>().Things, item16);
			}
		}
		if (CompareVersion(pGameRun.Version, "1.10.4") < 0)
		{
			foreach (Entity item17 in pGameRun.Entities.FindAll((Entity e) => e.Has<CharacterComponent>()))
			{
				if (item17.TryGet<StatusEffectComponent>(out var pComponent2) && pComponent2 != null && InteractableHelper.HasStatus(item17, "STATUS_PURIFY_01"))
				{
					StatusEffectInfo statusEffectInfo = pComponent2.Statuses["STATUS_PURIFY_01"];
					pComponent2.Statuses.Remove("STATUS_PURIFY_01");
					pComponent2.Statuses.Add("STATUS_TAROT_PURIFY_00", StatusEffectInfo.Create(statusEffectInfo.Duration, statusEffectInfo.TickDuration, statusEffectInfo.OriginEntityId));
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.11.0") < 0)
		{
			foreach (Entity item18 in pGameRun.Entities.FindAll((Entity e) => e.Has<EncounterComponent>() && e.TryGet<MapPropComponent>(out pComponent5) && pComponent5.ConfigName != null && pComponent5.ConfigName.StartsWith("MINE_CART")))
			{
				if (item18.TryGet<EncounterComponent>(out var pComponent3) && pComponent3.Properties != null && !item18.Get<EncounterComponent>().Properties.Contains(eEncounterProperties.UNNAVIGABLE))
				{
					item18.Get<EncounterComponent>().Properties.Add(eEncounterProperties.UNNAVIGABLE);
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.11.1") < 0 && pGameRun.DungeonState != null && pGameRun.VenueState != null)
		{
			VenueHelper.QueryVenuePartyEntities(pGameRun, pAliveOnly: false);
			pGameRun.VenueState.VenuePlayerNames.RemoveAll((string v) => pGameRun.Entities.Any((Entity e) => e.Guid == v) && CharacterHelper.IsDead(pGameRun.Entities.Find((Entity e) => e.Guid == v)));
		}
		if (CompareVersion(pGameRun.Version, "1.12.0") < 0 && _retrofitBaseMapAdventures.Contains(pGameRun.ConfigName))
		{
			foreach (Entity item19 in pGameRun.Entities.FindAll(delegate(Entity x)
			{
				if (x.TryGet<EncounterComponent>(out pComponent5))
				{
					eEncounterTypes type = pComponent5.Type;
					return type == eEncounterTypes.SAFE_CAMP || type == eEncounterTypes.SAFE_CABIN;
				}
				return false;
			}))
			{
				if (!item19.Has<SafeCampEncounterComponent>())
				{
					item19.Add<SafeCampEncounterComponent>(new SafeCampEncounterComponent());
				}
			}
			if (pGameRun.DungeonState != null && pGameRun.DungeonState.SafeCamp != eSafeCampType.NONE)
			{
				pGameRun.DungeonState.SafeCampComponent = new SafeCampEncounterComponent
				{
					Type = pGameRun.DungeonState.SafeCamp
				};
			}
		}
		if (CompareVersion(pGameRun.Version, "1.12.6") < 0)
		{
			foreach (Entity item20 in list2)
			{
				AvatarComponent avatarComponent = item20.Get<AvatarComponent>();
				Dictionary<eEquipmentSlots, bool> dictionary = avatarComponent.ItemSlotVisibility;
				if (dictionary == null)
				{
					dictionary = new Dictionary<eEquipmentSlots, bool>();
				}
				AvatarComponent avatarComponent2 = avatarComponent;
				if (avatarComponent2.EquipmentSlotVisibility == null)
				{
					avatarComponent2.EquipmentSlotVisibility = new Dictionary<eEquipmentSlots, eEquipmentVisibilityTypes>();
				}
				foreach (KeyValuePair<eEquipmentSlots, bool> item21 in dictionary)
				{
					avatarComponent.EquipmentSlotVisibility.TryAdd(item21.Key, item21.Value ? eEquipmentVisibilityTypes.SHOW : eEquipmentVisibilityTypes.HIDDEN_MANUAL);
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.12.8") < 0)
		{
			foreach (QuestState activeQuest in pGameRun.ActiveQuests)
			{
				_do(activeQuest.Data);
			}
			foreach (QuestData futureQuest in pGameRun.FutureQuests)
			{
				_do(futureQuest);
			}
		}
		if (CompareVersion(pGameRun.Version, "1.12.12") < 0)
		{
			Entity entity2 = pGameRun.Entities.FirstOrDefault((Entity x) => x.TryGet<CharacterComponent>(out pComponent5) && pComponent5.CharacterType == eCharacterTypes.COMPANION && pComponent5.ConfigName.StartsWith("JEREMY_KING_0"));
			if (entity2 != null)
			{
				entity2.Get<CharacterComponent>().ConfigName = "JEREMY_KING_00";
			}
		}
		if (CompareVersion(pGameRun.Version, "1.12.13") < 0)
		{
			foreach (Entity item22 in pGameRun.Entities.FindAll((Entity x) => x.TryGet<CharacterComponent>(out pComponent5) && pComponent5.CharacterType == eCharacterTypes.COMPANION && pComponent5.ConfigName.StartsWith("COMPANION_MIMIC_BASIC_")))
			{
				if (item22 == null || !item22.TryGet<StatusEffectComponent>(out var pComponent4))
				{
					continue;
				}
				Dictionary<string, StatusEffectInfo> statuses = pComponent4.Statuses;
				if (statuses == null || statuses.Count <= 0)
				{
					continue;
				}
				for (int num6 = 0; num6 < pComponent4.Statuses.Count; num6++)
				{
					string key = pComponent4.Statuses.ElementAt(num6).Key;
					if (key.StartsWith("STATUS_IMBUE_SHOCK_") && key != "STATUS_IMBUE_SHOCK_00")
					{
						StatusEffectInfo value3 = pComponent4.Statuses[key];
						pComponent4.Statuses.Remove(key);
						pComponent4.Statuses.Add("STATUS_IMBUE_SHOCK_00", value3);
						break;
					}
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.13.0") < 0)
		{
			_replaceSheep("SHEPHERD_SHEEP_01", "SHEPHERD_SHEEP_BASIC_00");
			_replaceSheep("SHEPHERD_SHEEP_HEAL_00", "SHEPHERD_SHEEP_SUPPORT_00");
			_replaceSheep("COMPANION_WOLF_02", "SHEPHERD_SHEEP_WOLF_00");
		}
		if (CompareVersion(pGameRun.Version, "1.13.1") >= 0)
		{
			return;
		}
		List<string> list4 = (from e in pGameRun.Entities.FindAll((Entity x) => x.TryGet<CharacterComponent>(out pComponent5) && pComponent5.TypeArgs != null && pComponent5.TypeArgs.StartsWith("COMPANION_BUMBLEBEE"))
			select e.Guid).ToList();
		List<string> ownedBumblebees = new List<string>();
		if (pGameRun.PlayerFollowers != null)
		{
			foreach (Entity item23 in list2)
			{
				Entity playerFollower = CoreHelper.GetPlayerFollower(item23.Guid, pGameRun.PlayerFollowers, pGameRun.Entities);
				if (playerFollower != null && list4.Contains(playerFollower.Guid))
				{
					ownedBumblebees.Add(playerFollower.Guid);
				}
			}
		}
		if (pGameRun.VenueState?.VenuePlayerNames == null)
		{
			return;
		}
		foreach (string bee in list4.Where((string b) => !ownedBumblebees.Contains(b)).ToList())
		{
			pGameRun.VenueState?.VenuePlayerNames.RemoveAll((string guid) => bee == guid);
		}
		pGameRun.VenueState.VenuePlayerNames = pGameRun.VenueState?.VenuePlayerNames.Distinct().ToList();
		static void _convertToPreviousQuestID(List<QuestState> pQuests)
		{
			foreach (QuestState item24 in pQuests.Where((QuestState x) => x.PreviousQuest != null))
			{
				item24.PreviousQuestID = item24.PreviousQuest.Data.ID;
				item24.PreviousQuest = null;
			}
		}
		static void _do(QuestData pData)
		{
			for (int i = 0; i < pData.QuestEndWorldTriggers.Length; i++)
			{
				if (pData.QuestEndWorldTriggers[i] == "SET_ENCOUNTER_SIEGE")
				{
					pData.QuestEndWorldTriggers[i + 1] = pData.QuestEndWorldTriggers[i + 1].Replace("|", ",");
				}
			}
		}
		string _fixDungeonID(string pDungenID)
		{
			string result = pDungenID;
			foreach (string item25 in badDungeonIDs)
			{
				Match match = Regex.Match(pDungenID, item25.Replace("*", "(NORMAL|HARD)") ?? "");
				if (match.Success)
				{
					result = "GENERIC_" + pDungenID.Replace("_" + match.Groups[1].Value + "_", "_");
				}
			}
			return result;
		}
		static void _parseThings(List<Thing> pThings, Entity pCharacter = null)
		{
			if (pThings != null && pThings.Count > 0)
			{
				foreach (Thing thing in pThings)
				{
					(string, string) tuple = WEAPON_CONFIG_NAME_CHANGES.FirstOrDefault(((string, string) x) => x.Item1 == thing.ConfigName);
					if (!string.IsNullOrEmpty(tuple.Item1))
					{
						if (pCharacter != null)
						{
							Thing equippedThing = EquipmentHelper.GetEquippedThing(pCharacter.Get<CharacterComponent>(), eEquipmentSlots.MAIN_HAND);
							if (equippedThing != null && equippedThing.Id == thing.Id)
							{
								EquipmentHelper.Unequip(equippedThing, pCharacter);
								thing.ConfigName = tuple.Item2;
								EquipmentHelper.Equip(thing, pCharacter);
							}
							else
							{
								thing.ConfigName = tuple.Item2;
							}
						}
						else
						{
							thing.ConfigName = tuple.Item2;
						}
					}
				}
			}
		}
		void _parseThings2(List<Thing> pThings, Entity pCharacter = null)
		{
			if (pThings != null && pThings.Count > 0)
			{
				foreach (Thing thing in pThings)
				{
					(string, string) tuple = weaponConfigNameChanges.FirstOrDefault(((string, string) x) => x.Item1 == thing.ConfigName);
					if (!string.IsNullOrEmpty(tuple.Item1))
					{
						if (pCharacter != null)
						{
							Thing equippedThing = EquipmentHelper.GetEquippedThing(pCharacter.Get<CharacterComponent>(), eEquipmentSlots.MAIN_HAND);
							if (equippedThing != null && equippedThing.Id == thing.Id)
							{
								EquipmentHelper.Unequip(equippedThing, pCharacter);
								thing.ConfigName = tuple.Item2;
								EquipmentHelper.Equip(thing, pCharacter);
							}
							else
							{
								thing.ConfigName = tuple.Item2;
							}
						}
						else
						{
							thing.ConfigName = tuple.Item2;
						}
					}
				}
			}
		}
		void _replaceSheep(string pOldSheep, string pNewSheep)
		{
			foreach (Entity item26 in pGameRun.Entities.FindAll((Entity x) => x.TryGet<CharacterComponent>(out pComponent5) && pComponent5.TypeArgs == pOldSheep))
			{
				CharacterComponent characterComponent2 = item26.Get<CharacterComponent>();
				characterComponent2.TypeArgs = pNewSheep;
				characterComponent2.CharacterType = eCharacterTypes.COMPANION;
				characterComponent2.ConfigName = Env.Configs.Followers[pNewSheep].ConfigName;
				characterComponent2.CurrentHealth = CharacterHelper.GetMaxHealth(item26);
			}
		}
	}

	private static void _tryRetrofitSubMapStates(GameRunData pGameRun)
	{
		if (_retrofitBaseAdventures.Contains(pGameRun.ConfigName) && string.IsNullOrEmpty(pGameRun.AdventureState.ActiveMapID))
		{
			pGameRun.AdventureState.ActiveMapID = pGameRun.ConfigName;
			foreach (Entity item in pGameRun.Entities.Where((Entity x) => x.Has<AdventureComponent>()))
			{
				item.Get<AdventureComponent>().MapID = pGameRun.ConfigName;
			}
			MapState value = new MapState
			{
				MapVariant = pGameRun.ConfigName,
				GameStageIndex = pGameRun.GameStageIndex,
				GameStageRoundStart = pGameRun.GameStageRoundStart,
				TimeOfDay = pGameRun.AdventureState.TimeOfDay,
				TimeOfDayLength = pGameRun.AdventureState.TimeOfDayLength,
				TimeOfDayTimeline = pGameRun.AdventureState.TimeOfDayTimeline,
				CurrentWeather = pGameRun.AdventureState.CurrentWeather,
				CurrentTimeOfDayIndex = pGameRun.AdventureState.CurrentTimeOfDayIndex,
				CustomTimelineEvents = pGameRun.AdventureState.CustomTimelineEvents,
				ExpiredCustomTimelineEvents = pGameRun.AdventureState.ExpiredCustomTimelineEvents,
				EncounterSpawnHexCooldown = pGameRun.AdventureState.EncounterSpawnHexCooldown,
				DisabledZones = pGameRun.AdventureState.DisabledZones,
				ActiveScourges = pGameRun.ActiveScourges,
				MapGenEncounterSpots = pGameRun.AdventureState.MapGenPool.MapGenEncounterSpots
			};
			pGameRun.AdventureState.MapStates = new Dictionary<string, MapState>();
			pGameRun.AdventureState.MapStates.Add(pGameRun.ConfigName, value);
			foreach (QuestState activeQuest in pGameRun.ActiveQuests)
			{
				activeQuest.MapID = pGameRun.ConfigName;
			}
			foreach (QuestState completedQuest in pGameRun.CompletedQuests)
			{
				completedQuest.MapID = pGameRun.ConfigName;
			}
			foreach (QuestState failedQuest in pGameRun.FailedQuests)
			{
				failedQuest.MapID = pGameRun.ConfigName;
			}
			pGameRun.AdventureState.TimeOfDayTimeline = null;
			pGameRun.AdventureState.CustomTimelineEvents = null;
			pGameRun.AdventureState.ExpiredCustomTimelineEvents = null;
			pGameRun.AdventureState.EncounterSpawnHexCooldown = null;
			pGameRun.AdventureState.DisabledZones = null;
			pGameRun.ActiveScourges = null;
			pGameRun.AdventureState.MapGenPool.MapGenEncounterSpots = null;
			if (pGameRun.ConfigName.Equals("STORY_1_4"))
			{
				foreach (Entity item2 in pGameRun.Entities.Where((Entity x) => x.Has<HexComponent>()))
				{
					HexComponent hexComponent = item2.Get<HexComponent>();
					if (hexComponent.ZoneName.Equals("ISLAND_0_MAIN_ZONE_1"))
					{
						hexComponent.ZoneName = "ISLAND_0_MAIN_ZONE_0";
					}
				}
			}
			if (pGameRun.ConfigName.Equals("STORY_1_1"))
			{
				QuestState questState = pGameRun.ActiveQuests.FirstOrDefault((QuestState x) => x.Data.ID == "STORY_1_1_REACH_EAST_FOREST");
				if (questState != null && questState.Data.QuestEndWorldTriggers[0] != "SET_GAME_STAGE")
				{
					questState.Data.QuestEndWorldTriggers[0] = "SET_GAME_STAGE";
					questState.Data.QuestEndWorldTriggers[1] = "3";
				}
				QuestData questData = pGameRun.FutureQuests.FirstOrDefault((QuestData x) => x.ID == "STORY_1_1_REACH_EAST_FOREST");
				if (!string.IsNullOrEmpty(questData.ID) && questData.QuestEndWorldTriggers[0] != "SET_GAME_STAGE")
				{
					questData.QuestEndWorldTriggers[0] = "SET_GAME_STAGE";
					questData.QuestEndWorldTriggers[1] = "3";
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.5.10") < 0)
		{
			if (pGameRun.ConfigName == "STORY_1_1")
			{
				foreach (QuestState activeQuest2 in pGameRun.ActiveQuests)
				{
					switch (activeQuest2.Data.ID)
					{
					case "STORY_1_1_DUNGEON_SKIP":
					case "STORY_1_1_REACH_EAST_FOREST":
					case "STORY_1_1_COMPLETE_TASKS":
					case "STORY_1_1_CLEAR_BANDIT_KING":
						activeQuest2.MapID = (pGameRun.AdventureState.MapStates.ContainsKey("STORY_1_1_ACT2") ? "STORY_1_1_ACT2" : "STORY_1_1");
						break;
					default:
						activeQuest2.MapID = ((activeQuest2.Data.QuestType == eQuests.SIDE_MISSION) ? pGameRun.AdventureState.ActiveMapID : pGameRun.ConfigName);
						break;
					}
				}
				foreach (QuestState completedQuest2 in pGameRun.CompletedQuests)
				{
					completedQuest2.MapID = pGameRun.ConfigName;
				}
				foreach (QuestState failedQuest2 in pGameRun.FailedQuests)
				{
					failedQuest2.MapID = pGameRun.ConfigName;
				}
			}
			else if (pGameRun.ConfigName == "STORY_1_5")
			{
				foreach (QuestState activeQuest3 in pGameRun.ActiveQuests)
				{
					string iD = activeQuest3.Data.ID;
					if (iD == "STORY_1_5_3_LEAVE_HELL" || iD == "STORY_1_5_3_CLEAR_HELL_CAVE")
					{
						activeQuest3.MapID = (pGameRun.AdventureState.MapStates.ContainsKey("STORY_1_5_HELL") ? "STORY_1_5_HELL" : "STORY_1_5");
					}
					else
					{
						activeQuest3.MapID = pGameRun.ConfigName;
					}
				}
				foreach (QuestState completedQuest3 in pGameRun.CompletedQuests)
				{
					completedQuest3.MapID = pGameRun.ConfigName;
				}
				foreach (QuestState failedQuest3 in pGameRun.FailedQuests)
				{
					failedQuest3.MapID = pGameRun.ConfigName;
				}
			}
			else
			{
				foreach (QuestState activeQuest4 in pGameRun.ActiveQuests)
				{
					activeQuest4.MapID = pGameRun.AdventureState.ActiveMapID;
				}
				foreach (QuestState completedQuest4 in pGameRun.CompletedQuests)
				{
					completedQuest4.MapID = pGameRun.AdventureState.ActiveMapID;
				}
				foreach (QuestState failedQuest4 in pGameRun.FailedQuests)
				{
					failedQuest4.MapID = pGameRun.AdventureState.ActiveMapID;
				}
			}
			foreach (Entity item3 in pGameRun.Entities.Where((Entity x) => x.Has<QuestBoardEncounterComponent>()))
			{
				if (!item3.TryGet<QuestBoardEncounterComponent>(out var pComponent))
				{
					continue;
				}
				List<AdventureMission> quests = pComponent.Quests;
				if (quests == null || quests.Count <= 0)
				{
					continue;
				}
				foreach (AdventureMission quest in pComponent.Quests)
				{
					quest.Quest.MapID = item3.Get<AdventureComponent>().MapID;
				}
			}
		}
		if (CompareVersion(pGameRun.Version, "1.5.12") < 0 && pGameRun.AdventureState.Markers != null)
		{
			pGameRun.AdventureState.Markers.Clear();
		}
		if (CompareVersion(pGameRun.Version, "1.10.4") >= 0)
		{
			return;
		}
		if (pGameRun.ChaosState != null)
		{
			Dictionary<string, MapState> mapStates = pGameRun.AdventureState.MapStates;
			if (mapStates != null && mapStates.Count > 0)
			{
				using (MemoryStream memoryStream = new MemoryStream())
				{
					JsonHelper.Serialize(memoryStream, pGameRun.ChaosState);
					foreach (KeyValuePair<string, MapState> mapState in pGameRun.AdventureState.MapStates)
					{
						memoryStream.Position = 0L;
						mapState.Value.ChaosState = JsonHelper.Deserialize<ChaosState>(memoryStream);
					}
				}
				pGameRun.ChaosState = null;
			}
		}
		Dictionary<string, MapState> mapStates2 = pGameRun.AdventureState.MapStates;
		if (mapStates2 == null || mapStates2.Count <= 0)
		{
			return;
		}
		pGameRun.AdventureState.TotalRoundCount = pGameRun.RoundCount;
		foreach (KeyValuePair<string, MapState> mapState2 in pGameRun.AdventureState.MapStates)
		{
			mapState2.Value.RoundCount = pGameRun.RoundCount;
		}
	}

	public static bool IsManualSavingAllowed(Env pEnv)
	{
		if (pEnv.GameRun.GameDifficulty != eGameDifficulties.MASTER && pEnv.GameRun.GameDifficulty != eGameDifficulties.GAUNTLET)
		{
			return pEnv.GameRun.ConfigName != "SIDE_ADVENTURE_DARK_CARNIVAL";
		}
		return false;
	}
}
